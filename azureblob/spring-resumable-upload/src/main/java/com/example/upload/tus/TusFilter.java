package com.example.upload.tus;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Enforces tus version negotiation and decorates every response with the
 * Tus-Resumable header, per tus.io 1.0.0 §2.5 / §4.
 */
@Component
@Order(0)
public class TusFilter extends OncePerRequestFilter {

    public static final String VERSION = "1.0.0";
    public static final String H_RESUMABLE = "Tus-Resumable";
    public static final String H_VERSION = "Tus-Version";

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        String path = req.getRequestURI();
        if (!path.startsWith("/files")) {
            chain.doFilter(req, res);
            return;
        }
        boolean isOptions = "OPTIONS".equalsIgnoreCase(req.getMethod());
        if (!isOptions) {
            String requested = req.getHeader(H_RESUMABLE);
            if (!VERSION.equals(requested)) {
                res.setStatus(HttpServletResponse.SC_PRECONDITION_FAILED);
                res.setHeader(H_VERSION, VERSION);
                return;
            }
            res.setHeader(H_RESUMABLE, VERSION);
        }
        chain.doFilter(req, res);
    }
}
