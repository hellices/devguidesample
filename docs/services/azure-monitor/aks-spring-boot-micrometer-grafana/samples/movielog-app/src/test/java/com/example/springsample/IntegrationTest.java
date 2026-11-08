package com.example.springsample;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.BDDMockito.given;

import java.util.List;
import java.util.Optional;

import com.example.springsample.member.MemberService;
import com.example.springsample.movie.omdb.ExternalRatings;
import com.example.springsample.movie.omdb.OmdbClient;
import com.example.springsample.movie.tmdb.TmdbClient;
import com.example.springsample.movie.tmdb.TmdbDtos;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

/**
 * Full application with an in-memory database; TMDB and OMDb are mocked. Every subclass shares one context.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Transactional
public abstract class IntegrationTest {

	@Autowired
	protected MockMvc mockMvc;

	@Autowired
	protected MemberService memberService;

	@MockitoBean
	protected TmdbClient tmdb;

	@MockitoBean
	protected OmdbClient omdb;

	@BeforeEach
	void enableMovieApis() {
		given(tmdb.isEnabled()).willReturn(true);
		given(omdb.isEnabled()).willReturn(true);
		given(omdb.ratings(anyString())).willReturn(Optional.empty());
	}

	protected String register(String username) {
		memberService.register(username, "password123", username + "님");
		return username;
	}

	/** Makes TMDB know a movie (and OMDb its ratings when {@code rottenTomatoes} is set). */
	protected void stubMovie(long tmdbId, String title, String imdbId, Integer rottenTomatoes) {
		given(tmdb.details(tmdbId)).willReturn(Optional.of(new TmdbDtos.MovieDetails(tmdbId, title, title + " (original)",
				"2019-05-30", "/poster" + tmdbId + ".jpg", title + " 줄거리", 132,
				List.of(new TmdbDtos.Genre(18, "드라마")), imdbId)));
		if (rottenTomatoes != null) {
			given(omdb.ratings(imdbId)).willReturn(Optional.of(new ExternalRatings(rottenTomatoes, 8.5, 96)));
		}
	}

}
