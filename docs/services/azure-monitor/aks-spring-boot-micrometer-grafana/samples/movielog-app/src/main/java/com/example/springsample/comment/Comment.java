package com.example.springsample.comment;

import java.time.Instant;

import com.example.springsample.member.Member;
import com.example.springsample.review.Review;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

@Entity
@Table(name = "comments", indexes = @Index(name = "idx_comments_review_id", columnList = "review_id"))
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Comment {

	public static final int CONTENT_MAX_LENGTH = 1_000;

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "review_id", nullable = false)
	private Review review;

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "author_id", nullable = false)
	private Member author;

	@Column(nullable = false, length = CONTENT_MAX_LENGTH)
	private String content;

	@CreatedDate
	@Column(nullable = false, updatable = false)
	private Instant createdAt;

	public Comment(Review review, Member author, String content) {
		this.review = review;
		this.author = author;
		this.content = content;
	}

	public boolean isWrittenBy(String username) {
		return author.getUsername().equals(username);
	}

}
