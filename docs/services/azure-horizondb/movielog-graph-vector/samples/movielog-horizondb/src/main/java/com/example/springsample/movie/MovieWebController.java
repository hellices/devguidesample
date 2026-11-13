package com.example.springsample.movie;

import java.util.List;

import com.example.springsample.discover.DiscoverService;
import com.example.springsample.discover.DiscoverUnavailableException;
import com.example.springsample.review.ReviewService;
import lombok.RequiredArgsConstructor;
import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;

@Controller
@RequiredArgsConstructor
class MovieWebController {

	private static final Logger logger = LoggerFactory.getLogger(MovieWebController.class);

	private final MovieService movieService;

	private final ReviewService reviewService;

	private final DiscoverService discoverService;

	@GetMapping("/movies")
	String search(@RequestParam(required = false) @Nullable String q, Model model) {
		String query = (q == null) ? "" : q.strip();
		model.addAttribute("q", query);
		model.addAttribute("searchAvailable", movieService.isSearchAvailable());
		if (StringUtils.hasText(query) && movieService.isSearchAvailable()) {
			try {
				model.addAttribute("result", movieService.search(query, 1));
			}
			catch (MovieApiUnavailableException ex) {
				// The query is user input; it is not logged so it cannot forge log lines.
				logger.warn("Movie search failed: {}", ex.getMessage());
				model.addAttribute("searchFailed", true);
			}
		}
		return "movies/search";
	}

	@GetMapping("/movies/{tmdbId}")
	String detail(@PathVariable long tmdbId, @AuthenticationPrincipal @Nullable UserDetails user, Model model) {
		model.addAttribute("movie", movieService.viewMovie(tmdbId));
		model.addAttribute("slice", reviewService.forMovie(tmdbId, null, ReviewService.DEFAULT_SLICE_SIZE));
		model.addAttribute("pageSize", ReviewService.DEFAULT_SLICE_SIZE);
		model.addAttribute("myReviewId", (user == null) ? null : reviewService.findOwnReviewId(tmdbId, user.getUsername()));
		model.addAttribute("overviewSource", discoverService.overviewSource(tmdbId));
		try {
			model.addAttribute("similar", discoverService.similar(tmdbId, 6));
		}
		catch (DiscoverUnavailableException ex) {
			model.addAttribute("similar", List.of());
		}
		return "movies/detail";
	}

}
