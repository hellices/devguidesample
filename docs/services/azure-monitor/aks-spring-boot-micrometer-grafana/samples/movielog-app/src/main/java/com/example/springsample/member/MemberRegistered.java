package com.example.springsample.member;

/** A new member signed up; delivered to listeners after the transaction commits. */
public record MemberRegistered(long memberId) {
}
