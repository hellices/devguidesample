package com.example.springsample.comment;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

public interface CommentRepository extends JpaRepository<Comment, Long> {

	@Query("""
			select new com.example.springsample.comment.CommentResponse(
				c.id, c.content, a.username, a.nickname, c.createdAt)
			from Comment c join c.author a
			where c.review.id = :reviewId
			order by c.id""")
	List<CommentResponse> findResponsesByReviewId(Long reviewId);

	@EntityGraph(attributePaths = { "author", "review" })
	Optional<Comment> findWithAuthorById(Long id);

	@Modifying(flushAutomatically = true, clearAutomatically = true)
	@Query("delete from Comment c where c.review.id = :reviewId")
	void deleteByReviewId(Long reviewId);

}
