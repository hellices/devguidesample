package com.example.springsample.metrics;

import java.util.Locale;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/**
 * Where a business action came from, used as the low-cardinality {@code channel} tag.
 * Resolved from the current HTTP request, so services do not need to pass it along.
 */
enum Channel {

	/** Thymeleaf pages. */
	WEB,
	/** REST API under {@code /api}. */
	API,
	/** No HTTP request (tests, batch jobs). */
	INTERNAL;

	String tagValue() {
		return name().toLowerCase(Locale.ROOT);
	}

	static Channel current() {
		RequestAttributes attributes = RequestContextHolder.getRequestAttributes();
		if (!(attributes instanceof ServletRequestAttributes servletAttributes)) {
			return INTERNAL;
		}
		HttpServletRequest request = servletAttributes.getRequest();
		String path = request.getRequestURI().substring(request.getContextPath().length());
		return path.startsWith("/api/") ? API : WEB;
	}

}
