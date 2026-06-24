package com.example.upload.tus;

import com.example.upload.tus.TusUploadService.Status;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;

/**
 * tus.io 1.0.0 endpoints (core + creation + termination).
 *
 * Headers handled:
 *   - Tus-Resumable          (added/validated by TusFilter)
 *   - Tus-Version, Tus-Extension, Tus-Max-Size  (OPTIONS)
 *   - Upload-Length          (POST)
 *   - Upload-Metadata        (POST, echoed on HEAD)
 *   - Upload-Offset          (PATCH request + HEAD/PATCH response)
 *   - Content-Type: application/offset+octet-stream  (PATCH)
 *   - Content-Length         (PATCH; chunked encoding rejected with 411)
 */
@RestController
@RequestMapping("/files")
public class TusController {

    private static final long MAX_UPLOAD_BYTES = 5L * 1024 * 1024 * 1024; // 5 GiB

    private final TusUploadService service;

    public TusController(TusUploadService service) {
        this.service = service;
    }

    @RequestMapping(method = RequestMethod.OPTIONS)
    public ResponseEntity<Void> options() {
        HttpHeaders h = new HttpHeaders();
        h.add("Tus-Version", TusFilter.VERSION);
        h.add("Tus-Extension", "creation,termination");
        h.add("Tus-Max-Size", Long.toString(MAX_UPLOAD_BYTES));
        return new ResponseEntity<>(h, HttpStatus.NO_CONTENT);
    }

    @PostMapping
    public ResponseEntity<Void> create(
            @RequestHeader("Upload-Length") long uploadLength,
            @RequestHeader(value = "Upload-Metadata", required = false) String metadata,
            HttpServletRequest req) {
        if (uploadLength > MAX_UPLOAD_BYTES) {
            throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE);
        }
        String id = service.create(uploadLength, metadata);
        HttpHeaders h = new HttpHeaders();
        h.add(HttpHeaders.LOCATION, req.getRequestURL().append('/').append(id).toString());
        return new ResponseEntity<>(h, HttpStatus.CREATED);
    }

    @RequestMapping(value = "/{id}", method = RequestMethod.HEAD)
    public ResponseEntity<Void> head(@PathVariable String id) {
        Status s = service.status(id);
        HttpHeaders h = new HttpHeaders();
        h.add("Upload-Offset", Long.toString(s.offset()));
        h.add("Upload-Length", Long.toString(s.length()));
        h.add(HttpHeaders.CACHE_CONTROL, "no-store");
        if (!s.metadata().isEmpty()) h.add("Upload-Metadata", s.metadata());
        return new ResponseEntity<>(h, HttpStatus.OK);
    }

    @PatchMapping(value = "/{id}", consumes = "application/offset+octet-stream")
    public ResponseEntity<Void> patch(
            @PathVariable String id,
            @RequestHeader("Upload-Offset") long offset,
            @RequestHeader(value = "Content-Length", required = false) Long contentLength,
            HttpServletRequest req) throws IOException {
        if (contentLength == null || contentLength < 0) {
            throw new ResponseStatusException(HttpStatus.LENGTH_REQUIRED);
        }
        // Pass the request InputStream straight through to the Azure SDK — no chunk-sized
        // byte[] is ever allocated. Tomcat/Netty read buffer (~8-64 KB) is the only memory
        // held during the PATCH, regardless of Content-Length.
        long newOffset = service.appendChunk(id, offset, req.getInputStream(), contentLength);
        HttpHeaders h = new HttpHeaders();
        h.add("Upload-Offset", Long.toString(newOffset));
        return new ResponseEntity<>(h, HttpStatus.NO_CONTENT);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable String id) {
        service.delete(id);
        return new ResponseEntity<>(HttpStatus.NO_CONTENT);
    }
}
