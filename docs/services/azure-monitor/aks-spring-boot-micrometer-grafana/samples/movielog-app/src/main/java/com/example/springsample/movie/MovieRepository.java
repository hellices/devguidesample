package com.example.springsample.movie;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

public interface MovieRepository extends JpaRepository<Movie, Long> {

	Optional<Movie> findByTmdbId(Long tmdbId);

	List<Movie> findByTmdbIdIn(Collection<Long> tmdbIds);

	/** Most viewed first; ties broken by id so the order is stable. */
	List<Movie> findByViewCountGreaterThanOrderByViewCountDescIdAsc(long minViews, Limit limit);

	@Modifying(flushAutomatically = true)
	@Query("update Movie m set m.viewCount = m.viewCount + 1 where m.id = :id")
	int incrementViewCount(Long id);

	@Query("select m.viewCount from Movie m where m.id = :id")
	long findViewCountById(Long id);

}
