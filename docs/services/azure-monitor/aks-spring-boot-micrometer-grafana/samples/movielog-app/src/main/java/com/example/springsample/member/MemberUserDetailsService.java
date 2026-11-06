package com.example.springsample.member;

import lombok.RequiredArgsConstructor;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
class MemberUserDetailsService implements UserDetailsService {

	private final MemberRepository members;

	@Override
	@Transactional(readOnly = true)
	public UserDetails loadUserByUsername(String username) {
		return members.findByUsername(username)
			.map(member -> User.withUsername(member.getUsername())
				.password(member.getPassword())
				.roles("USER")
				.build())
			.orElseThrow(() -> new UsernameNotFoundException(username));
	}

}
