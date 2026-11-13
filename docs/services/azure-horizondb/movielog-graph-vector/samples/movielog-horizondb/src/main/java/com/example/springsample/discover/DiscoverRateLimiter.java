package com.example.springsample.discover;

import java.time.Clock;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/**
 * Fixed one-minute windows per client address and for all clients, checked before each query embedding so that
 * anonymous traffic cannot spend Azure OpenAI quota without bound. Counts live in Pod memory, so the effective
 * limits scale with the replica count. Each minute gets a fresh {@link Window} that holds at most
 * {@code maxTrackedClients} addresses; new addresses beyond that are refused until the next minute.
 */
@Component
class DiscoverRateLimiter {

	static final int MAX_TRACKED_CLIENTS = 10_000;

	private final DiscoverRateLimitProperties properties;

	private final Clock clock;

	private final int maxTrackedClients;

	private final AtomicReference<Window> current = new AtomicReference<>(new Window(Long.MIN_VALUE));

	@Autowired
	DiscoverRateLimiter(DiscoverRateLimitProperties properties, Clock clock) {
		this(properties, clock, MAX_TRACKED_CLIENTS);
	}

	DiscoverRateLimiter(DiscoverRateLimitProperties properties, Clock clock, int maxTrackedClients) {
		this.properties = properties;
		this.clock = clock;
		this.maxTrackedClients = maxTrackedClients;
	}

	/** Counts one search for the client, or returns false without counting when a cap is reached. */
	boolean tryAcquire(String client) {
		long minute = clock.millis() / 60_000;
		// Windows only move forward; a request that read the clock just before a rollover counts in the newer one.
		Window window = current.updateAndGet(w -> (w.minute < minute) ? new Window(minute) : w);
		return window.tryAcquire(client, properties.perClientPerMinute(), properties.totalPerMinute(),
				maxTrackedClients);
	}

	/** All counts of one minute. Counters are never reset, so every check within a window is bounded. */
	private static final class Window {

		final long minute;

		final ConcurrentMap<String, AtomicInteger> clients = new ConcurrentHashMap<>();

		final AtomicInteger total = new AtomicInteger();

		Window(long minute) {
			this.minute = minute;
		}

		boolean tryAcquire(String client, int perClient, int totalLimit, int maxClients) {
			if (totalLimit > 0 && total.get() >= totalLimit) {
				return false;
			}
			AtomicInteger count = clients.get(client);
			if (count == null) {
				if (clients.size() >= maxClients) {
					return false;
				}
				count = clients.computeIfAbsent(client, key -> new AtomicInteger());
			}
			if (!tryIncrement(count, perClient)) {
				return false;
			}
			if (!tryIncrement(total, totalLimit)) {
				count.decrementAndGet();
				return false;
			}
			return true;
		}

		private static boolean tryIncrement(AtomicInteger count, int limit) {
			if (limit <= 0) {
				count.incrementAndGet();
				return true;
			}
			return count.getAndUpdate(value -> (value < limit) ? value + 1 : value) < limit;
		}

	}

}
