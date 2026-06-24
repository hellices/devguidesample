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

        int blockIndex = blocks.getUncommittedBlocks().size();
        String blockId = encodeBlockId(blockIndex);
        // Stream the request body straight to Azure (no full-chunk buffering in heap).
        // BinaryData.fromStream(stream, length) marks the payload as non-replayable, so the
        // SDK retry policy short-circuits — client-side retry (HEAD + re-PATCH) is responsible
        // for transient Azure failures.
        client.stageBlock(blockId, BinaryData.fromStream(data, length));

        long newOffset = currentOffset + length;
        if (newOffset == uploadLength) {
            List<String> allIds = new ArrayList<>(blockIndex + 1);
            for (int i = 0; i <= blockIndex; i++) allIds.add(encodeBlockId(i));
            BlockBlobCommitBlockListOptions commitOpts =
                    new BlockBlobCommitBlockListOptions(allIds)
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

    static String encodeBlockId(int index) {
        String raw = BLOCK_ID_PREFIX + String.format("%08d", index);
        return Base64.getEncoder().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }

    public record Status(long length, long offset, String metadata) {}
}
