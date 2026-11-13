package com.example.springsample.discover;

import java.time.Clock;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicInteger;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/**
 * Fixed one-minute windows per client address and for all clients, checked before each query embedding so that
 * anonymous traffic cannot spend Azure OpenAI quota without bound. Counts live in Pod memory, so the effective
 * limits scale with the replica count. The client map is cleared once per minute and holds at most
 * {@code maxTrackedClients} addresses; new addresses beyond that are refused until the next minute.
 */
@Component
class DiscoverRateLimiter {

	static final int MAX_TRACKED_CLIENTS = 10_000;

	private final DiscoverRateLimitProperties properties;

	private final Clock clock;

	private final int maxTrackedClients;

	private final ConcurrentMap<String, AtomicInteger> clients = new ConcurrentHashMap<>();

	private final AtomicInteger total = new AtomicInteger();

	private volatile long minute = Long.MIN_VALUE;

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
		rollOver(clock.millis() / 60_000);
		int totalLimit = properties.totalPerMinute();
		if (totalLimit > 0 && total.get() >= totalLimit) {
			return false;
		}
		AtomicInteger count = clients.get(client);
		if (count == null) {
			if (clients.size() >= maxTrackedClients) {
				return false;
			}
			count = clients.computeIfAbsent(client, key -> new AtomicInteger());
		}
		if (!tryIncrement(count, properties.perClientPerMinute())) {
			return false;
		}
		if (!tryIncrement(total, totalLimit)) {
			count.decrementAndGet();
			return false;
		}
		return true;
	}

	private void rollOver(long now) {
		if (now != minute) {
			synchronized (this) {
				if (now != minute) {
					clients.clear();
					total.set(0);
					minute = now;
				}
			}
		}
	}

	private static boolean tryIncrement(AtomicInteger count, int limit) {
		if (limit <= 0) {
			count.incrementAndGet();
			return true;
		}
		return count.getAndUpdate(current -> (current < limit) ? current + 1 : current) < limit;
	}

}
