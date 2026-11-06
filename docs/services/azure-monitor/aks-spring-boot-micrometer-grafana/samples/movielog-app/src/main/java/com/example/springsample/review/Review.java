package com.example.springsample.review;

import java.time.Instant;

import com.example.springsample.member.Member;
import com.example.springsample.movie.Movie;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.DynamicUpdate;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

/** A member's review of a movie; one review per member and movie. Counters change through bulk updates. */
@Entity
@Table(name = "reviews",
		uniqueConstraints = @UniqueConstraint(name = "uk_reviews_movie_author", columnNames = { "movie_id", "author_id" }))
@EntityListeners(AuditingEntityListener.class)
@DynamicUpdate
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Review {

	public static final int TITLE_MAX_LENGTH = 200;

	public static final int CONTENT_MAX_LENGTH = 10_000;

	/** Ratings are half stars: 1 = 0.5 stars ... 10 = 5 stars. */
	public static final int MIN_RATING = 1;

	public static final int MAX_RATING = 10;

	/** 3.5 stars or more counts as "fresh" for the audience score. */
	public static final int FRESH_THRESHOLD = 7;

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "movie_id", nullable = false)
	private Movie movie;

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "author_id", nullable = false)
	private Member author;

	@Column(nullable = false)
	private int rating;

	@Column(nullable = false, length = TITLE_MAX_LENGTH)
	private String title;

	@Column(nullable = false, length = CONTENT_MAX_LENGTH)
	private String content;

	@Column(nullable = false)
	private long viewCount;

	@Column(nullable = false)
	private long commentCount;

	@CreatedDate
	@Column(nullable = false, updatable = false)
	private Instant createdAt;

	@LastModifiedDate
	@Column(nullable = false)
	private Instant updatedAt;

	public Review(Movie movie, Member author, int rating, String title, String content) {
		this.movie = movie;
		this.author = author;
		edit(rating, title, content);
	}

	public void edit(int rating, String title, String content) {
		if (rating < MIN_RATING || rating > MAX_RATING) {
			throw new IllegalArgumentException("Rating must be between 1 and 10 half stars: " + rating);
		}
		this.rating = rating;
		this.title = title;
		this.content = content;
	}

	public boolean isWrittenBy(String username) {
		return author.getUsername().equals(username);
	}

}
