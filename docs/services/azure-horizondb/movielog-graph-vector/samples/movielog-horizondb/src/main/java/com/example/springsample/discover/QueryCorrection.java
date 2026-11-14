package com.example.springsample.discover;

/**
 * A semantic search query after spelling correction.
 *
 * @param query the query as searched
 * @param from the words as typed
 * @param to the person name or movie title that replaced them
 */
public record QueryCorrection(String query, String from, String to) {
}
