package com.example.springsample.config;

import java.time.Clock;

import com.example.springsample.discover.EmbeddingProperties;
import com.example.springsample.metrics.MetricsProperties;
import com.example.springsample.movie.MovieApiProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties({ MovieApiProperties.class, MetricsProperties.class, EmbeddingProperties.class })
class AppConfig {

	@Bean
	Clock clock() {
		return Clock.systemUTC();
	}

}
