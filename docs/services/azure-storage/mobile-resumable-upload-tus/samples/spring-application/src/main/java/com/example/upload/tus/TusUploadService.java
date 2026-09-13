package com.example.upload.tus;

import com.azure.core.util.BinaryData;
import com.azure.storage.blob.BlobContainerClient;
import com.azure.storage.blob.models.BlobProperties;
import com.azure.storage.blob.models.BlobStorageException;
import com.azure.storage.blob.models.Block;
import com.azure.storage.blob.models.BlockList;
import com.azure.storage.blob.models.BlockListType;
import com.azure.storage.blob.options.BlockBlobCommitBlockListOptions;
import com.azure.storage.blob.options.BlockBlobSimpleUploadOptions;
import com.azure.storage.blob.specialized.BlockBlobClient;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * tus protocol → Azure Block Blob mapper.
 *
 * Mapping
 * -------
 *  POST  /files           → create empty committed blob carrying Upload-Length
 *                           and Upload-Metadata in its blob metadata.
 *  HEAD  /files/{id}      → length from blob metadata; offset from blob size
 *                           (committed) OR sum of uncommitted block sizes.
 *  PATCH /files/{id}      → stage one block; if cumulative offset reaches
 *                           length, commit block list preserving metadata.
 *  DELETE /files/{id}     → delete the blob (uncommitted blocks GC with it).
 *
 * State lives entirely in Azure (blob + uncommitted block list). The server
 * is stateless; restart is invisible to clients.
 */
@Service
public class TusUploadService {

    static final String META_LENGTH = "x_tus_upload_length";
    static final String META_METADATA = "x_tus_metadata";
    private static final String BLOCK_ID_PREFIX = "block-";

    private final BlobContainerClient container;

    public TusUploadService(BlobContainerClient container) {
        this.container = container;
    }

    public String create(long uploadLength, String tusMetadata) {
        if (uploadLength < 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "negative Upload-Length");
        }
        String id = UUID.randomUUID().toString();
        Map<String, String> meta = new HashMap<>();
        meta.put(META_LENGTH, Long.toString(uploadLength));
        if (tusMetadata != null && !tusMetadata.isEmpty()) {
            meta.put(META_METADATA, tusMetadata);
        }
        BlockBlobClient client = container.getBlobClient(id).getBlockBlobClient();
        BlockBlobSimpleUploadOptions opts =
                new BlockBlobSimpleUploadOptions(BinaryData.fromBytes(new byte[0]))
                        .setMetadata(meta);
        client.uploadWithResponse(opts, null, null);
        return id;
    }

    public Status status(String id) {
        BlockBlobClient client = container.getBlobClient(id).getBlockBlobClient();
        BlobProperties props = getPropsOrThrow(client);
        long length = Long.parseLong(props.getMetadata().get(META_LENGTH));
        String metadata = props.getMetadata().getOrDefault(META_METADATA, "");
        long offset;
        if (props.getBlobSize() >= length) {
            offset = length;
        } else {
            offset = sumUncommitted(client);
        }
        return new Status(length, offset, metadata);
    }

    public long appendChunk(String id, long expectedOffset, InputStream data, long length) {
        BlockBlobClient client = container.getBlobClient(id).getBlockBlobClient();
        BlobProperties props = getPropsOrThrow(client);
        long uploadLength = Long.parseLong(props.getMetadata().get(META_LENGTH));

        if (props.getBlobSize() >= uploadLength) {
            if (expectedOffset == uploadLength && length == 0) return uploadLength;
            throw new ResponseStatusException(HttpStatus.CONFLICT, "upload already complete");
        }

        BlockList blocks = client.listBlocks(BlockListType.UNCOMMITTED);
        long currentOffset = blocks.getUncommittedBlocks().stream()
                .mapToLong(Block::getSizeLong).sum();

        if (currentOffset != expectedOffset) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "offset mismatch: server=" + currentOffset + " client=" + expectedOffset);
        }
        if (currentOffset + length > uploadLength) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "chunk would exceed Upload-Length");
        }
        if (length == 0) {
            return currentOffset;
        }

        // Deterministic, offset-derived block id: a given offset always maps to the same
        // block id no matter which pod serves the PATCH or how the client retries. A duplicate
        // in-flight PATCH therefore re-stages identical bytes to the same block (idempotent),
        // instead of racing for a count-derived index that could collide across chunk sizes.
        String blockId = encodeBlockId(currentOffset);
        // Stream the request body straight to Azure (no full-chunk buffering in heap).
        // BinaryData.fromStream(stream, length) marks the payload as non-replayable, so the
        // SDK retry policy short-circuits — client-side retry (HEAD + re-PATCH) is responsible
        // for transient Azure failures.
        client.stageBlock(blockId, BinaryData.fromStream(data, length));

        long newOffset = currentOffset + length;
        if (newOffset == uploadLength) {
            // Commit the staged blocks ordered by their encoded offset. Reconstructing from the
            // pre-staging list plus this final block avoids an extra listBlocks round-trip and
            // stays correct even if chunk sizes varied across the upload.
            List<String> orderedIds = new ArrayList<>();
            for (Block b : blocks.getUncommittedBlocks()) orderedIds.add(b.getName());
            orderedIds.add(blockId);
            orderedIds.sort(Comparator.comparingLong(TusUploadService::decodeOffset));
            BlockBlobCommitBlockListOptions commitOpts =
                    new BlockBlobCommitBlockListOptions(orderedIds)
                            .setMetadata(props.getMetadata());
            client.commitBlockListWithResponse(commitOpts, null, null);
        }
        return newOffset;
    }

    public void delete(String id) {
        try {
            container.getBlobClient(id).delete();
        } catch (BlobStorageException e) {
            if (e.getStatusCode() != 404) throw e;
        }
    }

    private BlobProperties getPropsOrThrow(BlockBlobClient client) {
        try {
            return client.getProperties();
        } catch (BlobStorageException e) {
            if (e.getStatusCode() == 404) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "upload not found");
            }
            throw e;
        }
    }

    private long sumUncommitted(BlockBlobClient client) {
        return client.listBlocks(BlockListType.UNCOMMITTED)
                .getUncommittedBlocks().stream()
                .mapToLong(Block::getSizeLong).sum();
    }

    // Fixed-width, offset-derived block id: all ids in one upload share the same length,
    // satisfying Azure's equal-length block id constraint. 12 digits covers > 900 GiB.
    static String encodeBlockId(long offset) {
        String raw = BLOCK_ID_PREFIX + String.format("%012d", offset);
        return Base64.getEncoder().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }

    static long decodeOffset(String blockId) {
        String raw = new String(Base64.getDecoder().decode(blockId), StandardCharsets.UTF_8);
        return Long.parseLong(raw.substring(BLOCK_ID_PREFIX.length()));
    }

    public record Status(long length, long offset, String metadata) {}
}
