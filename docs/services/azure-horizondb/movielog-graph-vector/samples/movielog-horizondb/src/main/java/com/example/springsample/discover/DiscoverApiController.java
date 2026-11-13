package com.example.springsample.discover;

import java.util.List;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Discover", description = "HorizonDB 벡터 검색(DiskANN)과 Apache AGE 영화 그래프")
@RestController
@RequestMapping("/api/discover")
@RequiredArgsConstructor
class DiscoverApiController {

	private final DiscoverService discoverService;

	@Operation(summary = "의미 검색", description = "질문을 HorizonDB 안에서 임베딩하고 코사인 거리로 가까운 영화를 반환합니다.")
	@GetMapping("/search")
	List<MovieHit> search(
			@Parameter(description = "자연어 질의") @RequestParam @NotBlank @Size(max = DiscoverService.MAX_QUERY_LENGTH) String q,
			@RequestParam(defaultValue = "12") @Min(1) @Max(DiscoverService.MAX_RESULTS) int limit) {
		return discoverService.search(q, limit);
	}

	@Operation(summary = "비슷한 영화", description = "영화 문서 임베딩이 가까운 순으로 반환합니다.")
	@GetMapping("/movies/{tmdbId}/similar")
	List<MovieHit> similar(@PathVariable long tmdbId,
			@RequestParam(defaultValue = "8") @Min(1) @Max(DiscoverService.MAX_RESULTS) int limit) {
		return discoverService.similar(tmdbId, limit);
	}

	@Operation(summary = "영화 주변 그래프", description = "감독·배우·장르·SIMILAR_TO 이웃과 같은 인물의 다른 영화를 반환합니다.")
	@GetMapping("/graph/movies/{tmdbId}")
	GraphView movieGraph(@PathVariable long tmdbId) {
		return discoverService.movieGraph(tmdbId);
	}

	@Operation(summary = "영화 사이 연결 그래프", description = "주어진 영화들 사이의 공통 인물·장르와 SIMILAR_TO 관계를 반환합니다.")
	@GetMapping("/graph")
	GraphView graphAmong(@RequestParam @NotEmpty @Size(max = DiscoverService.MAX_RESULTS) List<Long> ids) {
		return discoverService.graphAmong(ids);
	}

}
