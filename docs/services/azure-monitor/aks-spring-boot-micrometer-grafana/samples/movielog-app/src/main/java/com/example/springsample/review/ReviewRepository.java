package com.example.springsample.review;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

public interface ReviewRepository extends JpaRepository<Review, Long> {

	String ROW = """
			select new com.example.springsample.review.ReviewRow(
				r.id, r.title, substring(r.content, 1, 160), r.rating, a.nickname,
				m.tmdbId, m.title, m.releaseDate, m.posterPath, r.viewCount, r.commentCount, r.createdAt)
			from Review r join r.author a join r.movie m
			""";

	@Query(ROW + "where r.id < :cursor order by r.id desc")
	List<ReviewRow> findSlice(long cursor, Limit limit);

	/** {@code pattern} must be lower case, with LIKE wildcards in the search term escaped by a backslash. */
	@Query(ROW + """
			where r.id < :cursor
				and (lower(r.title) like :pattern escape '\\'
					or lower(r.content) like :pattern escape '\\'
					or lower(m.title) like :pattern escape '\\'
					or lower(m.originalTitle) like :pattern escape '\\')
			order by r.id desc""")
	List<ReviewRow> searchSlice(long cursor, String pattern, Limit limit);

	@Query(ROW + "where m.tmdbId = :tmdbId and r.id < :cursor order by r.id desc")
	List<ReviewRow> findSliceByMovie(long tmdbId, long cursor, Limit limit);

	/** Fresh means 7 half stars (3.5 stars) or more, see {@link Review#FRESH_THRESHOLD}. */
	@Query("""
			select new com.example.springsample.review.ReviewStats(
				r.movie.id, count(r), avg(r.rating),
				sum(case when r.rating >= 7 then 1 else 0 end))
			from Review r
			where r.movie.id in :movieIds
			group by r.movie.id""")
	List<ReviewStats> statsByMovieIds(Collection<Long> movieIds);

	@EntityGraph(attributePaths = { "author", "movie" })
	Optional<Review> findWithAuthorAndMovieById(Long id);

	@Query("select r.id from Review r where r.movie.tmdbId = :tmdbId and r.author.username = :username")
	Optional<Long> findIdByMovieAndAuthor(long tmdbId, String username);

	@Modifying(flushAutomatically = true, clearAutomatically = true)
	@Query("update Review r set r.viewCount = r.viewCount + 1 where r.id = :id")
	int incrementViewCount(Long id);

	@Modifying(flushAutomatically = true, clearAutomatically = true)
	@Query("update Review r set r.commentCount = r.commentCount + :delta where r.id = :id")
	void adjustCommentCount(Long id, int delta);

}
