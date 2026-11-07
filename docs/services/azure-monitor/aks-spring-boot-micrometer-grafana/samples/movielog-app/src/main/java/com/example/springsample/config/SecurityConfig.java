package com.example.springsample.config;

import java.util.List;

import com.example.springsample.metrics.MetricsProperties;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBooleanProperty;
import org.springframework.boot.security.autoconfigure.web.servlet.PathRequest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.security.authorization.AuthorizationDecision;
import org.springframework.security.authorization.AuthorizationManager;
import org.springframework.security.authorization.AuthorizationManagers;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.CsrfConfigurer;
import org.springframework.security.crypto.factory.PasswordEncoderFactories;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.access.IpAddressAuthorizationManager;
import org.springframework.security.web.access.intercept.RequestAuthorizationContext;
import org.springframework.security.web.authentication.HttpStatusEntryPoint;
import org.springframework.security.web.authentication.LoginUrlAuthenticationEntryPoint;
import org.springframework.security.web.servlet.util.matcher.PathPatternRequestMatcher;
import org.springframework.security.web.util.matcher.AnyRequestMatcher;

@Configuration
@EnableWebSecurity
class SecurityConfig {

	@Bean
	PasswordEncoder passwordEncoder() {
		return PasswordEncoderFactories.createDelegatingPasswordEncoder();
	}

	@Bean
	@Order(1)
	@ConditionalOnBooleanProperty("spring.h2.console.enabled")
	SecurityFilterChain h2ConsoleFilterChain(HttpSecurity http) throws Exception {
		// The H2 console renders in frames and posts forms without CSRF tokens.
		http
			.securityMatcher(PathRequest.toH2Console())
			.authorizeHttpRequests(auth -> auth.anyRequest().authenticated())
			.exceptionHandling(ex -> ex.authenticationEntryPoint(new LoginUrlAuthenticationEntryPoint("/login")))
			.csrf(csrf -> csrf.disable())
			.headers(headers -> headers.frameOptions(frame -> frame.sameOrigin()));
		return http.build();
	}

	@Bean
	@Order(2)
	SecurityFilterChain defaultFilterChain(HttpSecurity http, MetricsProperties metrics) throws Exception {
		http
			.authorizeHttpRequests(auth -> auth
				.requestMatchers("/actuator/health/**", "/actuator/info", "/error").permitAll()
				// Prometheus scrapes without a login, so the endpoint is limited to known addresses.
				.requestMatchers("/actuator/prometheus").access(scrapeAccess(metrics))
				.requestMatchers("/css/**", "/js/**", "/favicon.ico").permitAll()
				.requestMatchers("/login", "/signup").permitAll()
				// Only reachable when springdoc is enabled (dev profile).
				.requestMatchers("/swagger-ui.html", "/swagger-ui/**", "/v3/api-docs/**").permitAll()
				.requestMatchers(HttpMethod.GET, "/", "/reviews", "/reviews/{id}", "/movies", "/movies/{tmdbId}").permitAll()
				.requestMatchers(HttpMethod.GET, "/api/reviews", "/api/reviews/{id}", "/api/reviews/{id}/comments",
						"/api/movies/search", "/api/movies/popular", "/api/movies/{tmdbId}", "/api/movies/{tmdbId}/reviews")
					.permitAll()
				.anyRequest().authenticated())
			.formLogin(form -> form
				.loginPage("/login")
				.defaultSuccessUrl("/reviews"))
			.logout(logout -> logout.logoutSuccessUrl("/reviews"))
			.exceptionHandling(ex -> ex
				.defaultAuthenticationEntryPointFor(new HttpStatusEntryPoint(HttpStatus.UNAUTHORIZED),
						PathPatternRequestMatcher.withDefaults().matcher("/api/**"))
				.defaultAuthenticationEntryPointFor(new HttpStatusEntryPoint(HttpStatus.UNAUTHORIZED),
						PathPatternRequestMatcher.withDefaults().matcher("/actuator/**"))
				.defaultAuthenticationEntryPointFor(new LoginUrlAuthenticationEntryPoint("/login"),
						AnyRequestMatcher.INSTANCE))
			// Token in an XSRF-TOKEN cookie so Swagger UI and fetch() can echo it as a header.
			.csrf(CsrfConfigurer::spa);
		return http.build();
	}

	private static AuthorizationManager<RequestAuthorizationContext> scrapeAccess(MetricsProperties metrics) {
		List<AuthorizationManager<RequestAuthorizationContext>> allowed = metrics.scrapeAllowedIps().stream()
			.<AuthorizationManager<RequestAuthorizationContext>>map(IpAddressAuthorizationManager::hasIpAddress)
			.toList();
		return AuthorizationManagers.anyOf(new AuthorizationDecision(false),
				allowed.toArray(AuthorizationManager[]::new));
	}

}
