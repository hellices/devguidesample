package com.example.springsample.discover;

import java.time.Clock;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicInteger;

import org.springframework.stereotype.Component;

/**
 * Fixed one-minute windows per client address and for all clients, checked before each query embedding so that
 * anonymous traffic cannot spend Azure OpenAI quota without bound. Counts live in Pod memory, so the effective
 * limits scale with the replica count.
 */
@Component
class DiscoverRateLimiter {

	private static final int MAX_TRACKED_CLIENTS = 10_000;

	private final DiscoverRateLimitProperties properties;

	private final Clock clock;

	private final ConcurrentMap<String, Window> clients = new ConcurrentHashMap<>();

	private volatile Window total = new Window(-1);

	DiscoverRateLimiter(DiscoverRateLimitProperties properties, Clock clock) {
		this.properties = properties;
		this.clock = clock;
	}

	/** Counts one search for the client, or returns false without counting when a cap is reached. */
	boolean tryAcquire(String client) {
		long minute = clock.millis() / 60_000;
		if (clients.size() > MAX_TRACKED_CLIENTS) {
			clients.values().removeIf(window -> window.minute != minute);
		}
		Window clientWindow = clients.compute(client,
				(key, window) -> (window == null || window.minute != minute) ? new Window(minute) : window);
		if (!clientWindow.tryIncrement(properties.perClientPerMinute())) {
			return false;
		}
		Window totalWindow = total;
		if (totalWindow.minute != minute) {
			synchronized (this) {
				if (total.minute != minute) {
					total = new Window(minute);
				}
				totalWindow = total;
			}
		}
		if (!totalWindow.tryIncrement(properties.totalPerMinute())) {
			clientWindow.count.decrementAndGet();
			return false;
		}
		return true;
	}

	private static final class Window {

		final long minute;

		final AtomicInteger count = new AtomicInteger();

		Window(long minute) {
			this.minute = minute;
		}

		boolean tryIncrement(int limit) {
			if (limit <= 0) {
				return true;
			}
			return count.getAndUpdate(current -> (current < limit) ? current + 1 : current) < limit;
		}

	}

}
