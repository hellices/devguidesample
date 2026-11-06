package com.example.springsample.common;

import java.util.List;
import java.util.function.Function;

import org.jspecify.annotations.Nullable;

/**
 * One slice of an infinitely scrolled list. Pass {@code nextCursor} back as {@code cursor}
 * to load the following items; it is {@code null} when there is nothing more to load.
 */
public record CursorResponse<T>(List<T> items, @Nullable Long nextCursor, boolean hasNext) {

	/** Builds a slice from a query that fetched {@code size + 1} rows to detect a next slice. */
	public static <T> CursorResponse<T> of(List<T> fetched, int size, Function<T, Long> idOf) {
		boolean hasNext = fetched.size() > size;
		List<T> items = hasNext ? fetched.subList(0, size) : fetched;
		Long nextCursor = hasNext ? idOf.apply(items.getLast()) : null;
		return new CursorResponse<>(List.copyOf(items), nextCursor, hasNext);
	}

}
