import { formatDateTime, starIcons } from './app.js';

/**
 * Infinite scrolling for every ".infinite" container: when its sentinel nears the viewport,
 * the next slice is fetched from data-api-url and appended using the renderer named by data-renderer.
 * The cursor parameter (data-cursor-param) is "cursor" for reviews and "page" for movie search.
 */

function setPoster(root, posterUrl, title) {
	const image = root.querySelector('img.poster');
	const placeholder = root.querySelector('.poster-empty');
	if (posterUrl) {
		image.src = posterUrl;
		image.alt = `${title} 포스터`;
		placeholder.remove();
	}
	else {
		image.remove();
		placeholder.setAttribute('aria-label', `${title} 포스터 없음`);
	}
}

const renderers = {
	review(container, review) {
		const item = document.getElementById('review-item-template').content.firstElementChild.cloneNode(true);
		const movie = review.movie;
		const posterLink = item.querySelector('.review-poster-link');
		posterLink.href = container.dataset.movieUrl + movie.tmdbId;
		posterLink.title = movie.title;
		setPoster(posterLink, movie.posterUrl, movie.title);
		item.querySelector('.review-link').href = container.dataset.reviewUrl + review.id;
		item.querySelector('.review-movie').textContent =
			movie.releaseYear ? `${movie.title} (${movie.releaseYear})` : movie.title;
		item.querySelector('.review-title').textContent = review.title;
		item.querySelector('.stars').replaceWith(starIcons(review.rating));
		item.querySelector('.review-excerpt').textContent = review.excerpt;
		item.querySelector('.review-author').textContent = review.authorNickname;
		const time = item.querySelector('time');
		time.dateTime = review.createdAt;
		time.textContent = formatDateTime(review.createdAt);
		item.querySelector('.review-views').textContent = review.viewCount;
		item.querySelector('.review-comments').textContent = review.commentCount;
		return item;
	},

	movie(container, movie) {
		const card = document.getElementById('movie-item-template').content.firstElementChild.cloneNode(true);
		card.href = container.dataset.movieUrl + movie.tmdbId;
		setPoster(card, movie.posterUrl, movie.title);
		card.querySelector('.movie-card-title').textContent = movie.title;
		card.querySelector('.movie-year').textContent = movie.releaseYear ?? '개봉일 미정';
		if (movie.reviewCount > 0) {
			card.querySelector('.movie-average').textContent = movie.averageRating;
			card.querySelector('.movie-review-count').textContent = movie.reviewCount;
			card.querySelector('.movie-local-rating').hidden = false;
		}
		return card;
	},
};

function setUp(container) {
	const items = container.querySelector('[data-items]');
	const sentinel = container.querySelector('[data-sentinel]');
	const loader = container.querySelector('[data-loader]');
	const errorBox = container.querySelector('[data-error]');
	const endMessage = container.querySelector('[data-end]');
	const render = renderers[container.dataset.renderer];
	const cursorParam = container.dataset.cursorParam;

	const baseParams = new URLSearchParams();
	for (const [key, value] of Object.entries(container.dataset)) {
		if (key.startsWith('param') && value) {
			baseParams.set(key.charAt(5).toLowerCase() + key.slice(6), value);
		}
	}

	let next = container.dataset.next || null;
	let hasNext = container.dataset.hasNext === 'true';
	let loading = false;
	endMessage.hidden = hasNext || items.children.length === 0;

	function nearViewport() {
		return sentinel.getBoundingClientRect().top < window.innerHeight + 400;
	}

	async function loadMore() {
		if (loading || !hasNext) {
			return;
		}
		loading = true;
		loader.hidden = false;
		errorBox.hidden = true;
		try {
			const params = new URLSearchParams(baseParams);
			if (next) {
				params.set(cursorParam, next);
			}
			const response = await fetch(`${container.dataset.apiUrl}?${params}`, { headers: { Accept: 'application/json' } });
			if (!response.ok) {
				throw new Error(`HTTP ${response.status}`);
			}
			const slice = await response.json();
			items.append(...slice.items.map((item) => render(container, item)));
			next = slice.nextCursor ?? slice.nextPage ?? null;
			hasNext = slice.hasNext;
		}
		catch (error) {
			console.error('Failed to load more items', error);
			errorBox.hidden = false;
			return;
		}
		finally {
			loading = false;
			loader.hidden = true;
		}
		endMessage.hidden = hasNext;
		// The observer only fires on changes, so keep loading while the page is still too short to scroll.
		if (hasNext && nearViewport()) {
			loadMore();
		}
	}

	container.querySelector('[data-retry]').addEventListener('click', loadMore);
	new IntersectionObserver((entries) => {
		if (entries.some((entry) => entry.isIntersecting)) {
			loadMore();
		}
	}, { rootMargin: '0px 0px 400px 0px' }).observe(sentinel);
}

document.querySelectorAll('.infinite').forEach(setUp);

