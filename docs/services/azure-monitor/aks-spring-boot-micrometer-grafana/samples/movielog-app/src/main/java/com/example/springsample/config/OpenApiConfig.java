package com.example.springsample.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
class OpenApiConfig {

	@Bean
	OpenAPI boardOpenApi() {
		return new OpenAPI().info(new Info()
			.title("Spring Sample 게시판 API")
			.version("v1")
			.description("""
					조회 API는 누구나 호출할 수 있습니다. 작성/수정/삭제는 세션 로그인이 필요합니다.
					같은 브라우저에서 [/login](/login)으로 먼저 로그인한 뒤 Try it out을 사용하세요.
					CSRF 토큰(XSRF-TOKEN 쿠키)은 Swagger UI가 자동으로 헤더에 넣습니다."""));
	}

}
