package com.example.springsample.movie;

import java.util.List;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Movies", description = "영화 검색과 정보 (TMDB, 평론가 점수는 OMDb)")
@RestController
@RequestMapping("/api/movies")
@RequiredArgsConstructor
class MovieApiController {

	private final MovieService movieService;

	@Operation(summary = "영화 검색 (무한 스크롤)",
			description = "TMDB에서 제목으로 검색합니다. 다음 결과는 응답의 nextPage를 page로 넘겨 요청합니다.")
	@GetMapping("/search")
	MovieSearchPage search(
			@Parameter(description = "영화 제목 (한국어/원제)") @RequestParam @NotBlank @Size(max = 100) String q,
			@Parameter(description = "1부터 시작") @RequestParam(defaultValue = "1") @Min(1) @Max(MovieService.MAX_SEARCH_PAGE) int page) {
		return movieService.search(q, page);
	}

	@Operation(summary = "영화 정보",
			description = "포스터, 로튼토마토/IMDb/메타크리틱 점수, 이 사이트의 평균 별점과 관객 신선도를 함께 반환합니다. 영화 조회수가 1 증가합니다.")
	@GetMapping("/{tmdbId}")
	MovieDetail get(@Parameter(description = "TMDB 영화 id") @PathVariable long tmdbId) {
		return movieService.viewMovie(tmdbId);
	}

	@Operation(summary = "인기 영화", description = "이 사이트에서 조회수가 많은 영화 순으로 반환합니다.")
	@GetMapping("/popular")
	List<PopularMovie> popular(@Parameter(description = "가져올 개수")
			@RequestParam(defaultValue = "10") @Min(1) @Max(MovieService.MAX_POPULAR) int limit) {
		return movieService.popular(limit);
	}

}
