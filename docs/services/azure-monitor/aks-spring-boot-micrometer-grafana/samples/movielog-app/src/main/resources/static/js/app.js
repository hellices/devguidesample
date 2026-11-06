const dateTimeFormat = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' });

/** Formats an ISO-8601 instant in the browser's time zone. */
export function formatDateTime(iso) {
	const date = new Date(iso);
	return Number.isNaN(date.getTime()) ? iso : dateTimeFormat.format(date);
}

export function formatTimes(root = document) {
	root.querySelectorAll('time[datetime]').forEach((time) => {
		time.textContent = formatDateTime(time.dateTime);
	});
}

/** Five star icons for a rating in half stars (1..10); mirrors the "stars" Thymeleaf fragment. */
export function starIcons(rating) {
	const stars = document.createElement('span');
	stars.className = 'stars';
	stars.title = `별점 ${rating / 2}`;
	stars.setAttribute('aria-label', `별점 ${rating / 2}점`);
	for (let i = 1; i <= 5; i++) {
		const icon = document.createElement('i');
		const half = rating === i * 2 - 1;
		if (rating >= i * 2 || half) {
			icon.classList.add('fill');
		}
		icon.textContent = half ? 'star_half' : 'star';
		stars.append(icon);
	}
	return stars;
}

formatTimes();

document.addEventListener('submit', (event) => {
	const message = event.target.dataset?.confirm;
	if (message && !window.confirm(message)) {
		event.preventDefault();
	}
});

document.querySelectorAll('[data-rating-text]').forEach((text) => {
	text.closest('fieldset').addEventListener('change', (event) => {
		if (event.target.matches('[data-rating-input]')) {
			text.textContent = `${(Number(event.target.value) / 2).toFixed(1)} / 5`;
		}
	});
});
