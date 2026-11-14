package com.example.springsample.member;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

@Entity
@Table(name = "members")
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Member {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(nullable = false, unique = true, length = 20)
	private String username;

	@Column(nullable = false, length = 100)
	private String password;

	@Column(nullable = false, length = 20)
	private String nickname;

	/** Identity of a member who signs in with an external provider, for example {@code entra:<tid>:<oid>}. */
	@Column(unique = true, length = 100)
	private String externalId;

	@CreatedDate
	@Column(nullable = false, updatable = false)
	private Instant createdAt;

	public Member(String username, String encodedPassword, String nickname) {
		this.username = username;
		this.password = encodedPassword;
		this.nickname = nickname;
	}

	public Member(String username, String encodedPassword, String nickname, String externalId) {
		this(username, encodedPassword, nickname);
		this.externalId = externalId;
	}

}
