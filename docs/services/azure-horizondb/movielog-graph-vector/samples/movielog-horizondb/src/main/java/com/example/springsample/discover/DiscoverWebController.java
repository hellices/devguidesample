package com.example.springsample.discover;

import java.util.List;

import com.example.springsample.movie.MovieService;
import lombok.RequiredArgsConstructor;
import org.jspecify.annotations.Nullable;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;

@Controller
@RequiredArgsConstructor
class DiscoverWebController {

	private static final int PAGE_RESULTS = 12;

	private final DiscoverService discoverService;

	private final MovieService movieService;

	@GetMapping("/discover")
	String search(@RequestParam(required = false) @Nullable String q, Model model) {
		String query = (q == null) ? "" : q.strip();
		model.addAttribute("q", query);
		if (StringUtils.hasText(query)) {
			try {
				List<MovieHit> hits = discoverService.search(query, PAGE_RESULTS);
				model.addAttribute("hits", hits);
				model.addAttribute("hitIds", hits.stream().map(hit -> String.valueOf(hit.tmdbId())).toList());
			}
			catch (DiscoverUnavailableException ex) {
				model.addAttribute("searchFailed", true);
			}
		}
		return "discover/search";
	}

	@GetMapping("/graph/movies/{tmdbId}")
	String graph(@PathVariable long tmdbId, Model model) {
		model.addAttribute("movie", movieService.getMovie(tmdbId));
		return "discover/graph";
	}

}
