// Renders /api/discover graph JSON with Cytoscape.js and the fCoSE layout (globals from the CDN),
// plus the same relations as a text list with links for keyboard and screen-reader users.
// Movie nodes show their TMDB poster; the legend chips filter relation types; tapping a node opens a detail
// panel, and a person can be expanded to their other movies (/api/discover/graph/people/{qid}).
const container = document.getElementById("graph");
const relationList = document.getElementById("graph-relations");
const detail = document.getElementById("graph-detail");

const COLORS = { Movie: "#6750a4", Person: "#e8a33d", Genre: "#2e7d6b", Similar: "#6750a4", Edge: "#c9c3d1" };
// Filter chip -> edge types it shows.
const FILTERS = { people: ["DIRECTED", "ACTED_IN"], genres: ["IN_GENRE"], similar: ["SIMILAR_TO"] };

function nodeData(node) {
	return {
		id: node.id,
		kind: node.kind,
		name: node.name,
		label: nodeLabel(node),
		tmdbId: node.tmdbId,
		year: node.year,
		qid: node.qid,
		posterUrl: node.posterUrl,
		focus: node.focus ? 1 : 0,
	};
}

function edgeData(edge) {
	return {
		id: `e${edge.id}`,
		source: edge.source,
		target: edge.target,
		type: edge.type,
		score: edge.score,
		label: edge.type === "SIMILAR_TO" && edge.score != null ? edge.score.toFixed(2) : "",
	};
}

// fCoSE includes label boxes in the overlap check; plain CoSE is the fallback if the extension did not load.
// "focus" pins the page's movie to the center; randomize=false keeps the current positions when expanding.
function layoutOptions(cy, { randomize = true } = {}) {
	const common = { animate: !randomize, animationDuration: 400, fit: true, padding: 30, nodeDimensionsIncludeLabels: true };
	// Short edges and moderate repulsion keep the drawing compact, so fit() zooms in further and labels stay legible.
	const edgeLength = (edge) => (edge.data("type") === "SIMILAR_TO" ? 110 : 80);
	if (window.cytoscapeFcose) {
		const options = {
			...common,
			name: "fcose",
			quality: "proof",
			randomize,
			nodeSeparation: 60,
			nodeRepulsion: () => 9000,
			idealEdgeLength: edgeLength,
			edgeElasticity: () => 0.3,
			gravity: 0.2,
			gravityRange: 4,
			numIter: 5000,
			packComponents: true,
			tile: true,
			tilingPaddingVertical: 20,
			tilingPaddingHorizontal: 20,
		};
		const focus = cy.nodes("[focus = 1]");
		if (container.dataset.layout === "focus" && focus.length === 1) {
			options.fixedNodeConstraint = [{ nodeId: focus.id(), position: { x: 0, y: 0 } }];
		}
		return options;
	}
	return { ...common, name: "cose", randomize, nodeRepulsion: () => 40000, idealEdgeLength: edgeLength, nodeOverlap: 40 };
}

const STYLE = [
	{
		selector: "node",
		style: {
			label: "data(label)",
			"font-size": 12,
			"text-wrap": "wrap",
			"text-max-width": 120,
			"text-valign": "bottom",
			"text-margin-y": 5,
			"text-background-color": "#ffffff",
			"text-background-opacity": 0.9,
			"text-background-padding": 2,
			"text-background-shape": "roundrectangle",
			// Labels too small to read are hidden instead of drawn as noise; zooming in shows them.
			"min-zoomed-font-size": 7,
			color: "#1d1b20",
			width: 18,
			height: 18,
		},
	},
	{ selector: 'node[kind = "Movie"]', style: { "background-color": COLORS.Movie, shape: "round-rectangle", width: 26, height: 38 } },
	{
		// [?field] is truthy; [field] would also match null and load "null" as a relative image URL.
		selector: 'node[kind = "Movie"][?posterUrl]',
		style: {
			"background-image": "data(posterUrl)",
			"background-fit": "cover",
			"background-image-crossorigin": "anonymous",
			"border-width": 1,
			"border-color": "#79747e",
		},
	},
	{ selector: 'node[kind = "Person"]', style: { "background-color": COLORS.Person, "font-size": 11 } },
	{ selector: 'node[kind = "Genre"]', style: { "background-color": COLORS.Genre, shape: "diamond", "font-size": 11 } },
	{
		selector: "node[focus = 1]",
		style: { width: 40, height: 58, "font-size": 14, "font-weight": "bold", "border-width": 3, "border-color": COLORS.Movie },
	},
	{ selector: "node.expanded", style: { "border-width": 3, "border-color": "#1d1b20" } },
	{ selector: "node:selected", style: { "overlay-color": COLORS.Movie, "overlay-opacity": 0.15, "overlay-padding": 6 } },
	{ selector: "edge", style: { width: 1, "line-color": COLORS.Edge, "curve-style": "bezier", opacity: 0.8 } },
	{ selector: 'edge[type = "ACTED_IN"]', style: { "line-color": COLORS.Person, width: 1.2, opacity: 0.55 } },
	{ selector: 'edge[type = "DIRECTED"]', style: { "line-color": COLORS.Person, width: 2.5 } },
	{ selector: 'edge[type = "SIMILAR_TO"]', style: { "line-color": COLORS.Similar, "line-style": "dashed", width: 2 } },
	// Similarity scores appear only on highlighted edges so they do not pile up on the canvas.
	{
		selector: 'edge.highlight[type = "SIMILAR_TO"]',
		style: {
			label: "data(label)",
			"font-size": 10,
			color: COLORS.Similar,
			"text-background-color": "#ffffff",
			"text-background-opacity": 0.9,
			"text-background-padding": 1,
		},
	},
	{ selector: ".faded", style: { opacity: 0.12 } },
	{ selector: "edge.highlight", style: { opacity: 1 } },
	{ selector: ".filtered", style: { display: "none" } },
];

const RELATION_NAMES = { DIRECTED: "감독", ACTED_IN: "출연", IN_GENRE: "장르", SIMILAR_TO: "비슷한 영화" };
const KIND_ORDER = { Movie: 0, Person: 1, Genre: 2 };

function nodeLabel(node) {
	return node.year ? `${node.name} (${node.year})` : node.name;
}

function nodeLink(node, base) {
	if (node.kind !== "Movie" || node.tmdbId == null || !base) {
		const span = document.createElement("span");
		span.textContent = nodeLabel(node);
		return span;
	}
	const link = document.createElement("a");
	link.className = "link";
	link.href = `${base}${node.tmdbId}`;
	link.textContent = nodeLabel(node);
	return link;
}

// One item per node: its neighbors grouped by relation type, in the order focus movies, movies, people, genres.
function renderRelationList(view, base) {
	if (!relationList) {
		return;
	}
	const byId = new Map(view.nodes.map((node) => [node.id, node]));
	const relations = new Map(view.nodes.map((node) => [node.id, new Map()]));
	for (const edge of view.edges) {
		for (const [from, to] of [[edge.source, edge.target], [edge.target, edge.source]]) {
			const neighbor = byId.get(to);
			const groups = relations.get(from);
			if (!neighbor || !groups) {
				continue;
			}
			if (!groups.has(edge.type)) {
				groups.set(edge.type, []);
			}
			groups.get(edge.type).push({ node: neighbor, score: edge.type === "SIMILAR_TO" ? edge.score : null });
		}
	}
	const ordered = [...view.nodes].sort((a, b) => (b.focus - a.focus) || (KIND_ORDER[a.kind] - KIND_ORDER[b.kind])
		|| nodeLabel(a).localeCompare(nodeLabel(b), "ko"));
	const list = document.createElement("ul");
	for (const node of ordered) {
		const groups = relations.get(node.id);
		if (!groups || groups.size === 0) {
			continue;
		}
		const item = document.createElement("li");
		item.append(nodeLink(node, base));
		const details = document.createElement("ul");
		for (const [type, neighbors] of groups) {
			const line = document.createElement("li");
			line.append(`${RELATION_NAMES[type] || type}: `);
			neighbors.forEach(({ node: neighbor, score }, index) => {
				if (index > 0) {
					line.append(", ");
				}
				line.append(nodeLink(neighbor, base));
				if (score != null) {
					line.append(` (${score.toFixed(2)})`);
				}
			});
			details.append(line);
		}
		item.append(details);
		list.append(item);
	}
	relationList.replaceChildren(list);
}

function link(text, href) {
	const anchor = document.createElement("a");
	anchor.className = "link";
	anchor.href = href;
	anchor.textContent = text;
	return anchor;
}

function moviesOf(node) {
	return node.neighborhood('node[kind = "Movie"]').not(".filtered")
		.map((movie) => movie.data("label"))
		.sort((a, b) => a.localeCompare(b, "ko"));
}

// Detail panel of the tapped node: poster and links for a movie, connected movies and an expand button for a
// person or genre. The panel is plain DOM, so it works with the keyboard and screen readers.
function showDetail(node, actions, expandedCount) {
	if (!detail) {
		return;
	}
	const data = node.data();
	const body = document.createElement("div");
	body.className = "row top-align";
	if (data.posterUrl) {
		const poster = document.createElement("img");
		poster.src = data.posterUrl;
		poster.alt = `${data.name} 포스터`;
		poster.className = "graph-detail-poster";
		body.append(poster);
	}
	const text = document.createElement("div");
	text.className = "max";
	const title = document.createElement("h6");
	title.className = "small";
	title.textContent = data.label;
	const kind = document.createElement("p");
	kind.className = "small-text secondary-text";
	kind.textContent = { Movie: "영화", Person: "인물", Genre: "장르" }[data.kind] || data.kind;
	text.append(title, kind);

	const buttons = document.createElement("nav");
	buttons.className = "wrap small-space";
	if (data.kind === "Movie" && data.tmdbId != null) {
		buttons.append(link("영화 정보", `${container.dataset.movieUrl}${data.tmdbId}`));
		if (container.dataset.graphUrl) {
			buttons.append(link("이 영화의 관계 그래프", `${container.dataset.graphUrl}${data.tmdbId}`));
		}
	} else {
		const movies = moviesOf(node);
		const list = document.createElement("p");
		list.className = "small-text";
		list.textContent = movies.length ? `그래프의 연결된 영화 ${movies.length}편: ${movies.join(", ")}` : "그래프에 보이는 연결 영화가 없습니다.";
		text.append(list);
		if (data.kind === "Person" && data.qid && container.dataset.personApiUrl) {
			const expand = document.createElement("button");
			expand.type = "button";
			expand.className = "small";
			const expanded = node.hasClass("expanded");
			expand.textContent = !expanded ? "다른 작품 펼치기"
				: expandedCount === 0 ? "모든 작품이 이미 그래프에 있습니다"
				: expandedCount != null ? `${expandedCount}편을 더했습니다` : "다른 작품을 펼쳤습니다";
			expand.disabled = expanded;
			expand.addEventListener("click", async () => {
				expand.disabled = true;
				expand.textContent = "불러오는 중…";
				if (await actions.expand(node) == null) {
					expand.textContent = "불러오지 못했습니다";
					expand.disabled = false;
				}
			});
			buttons.append(expand);
		}
	}
	text.append(buttons);
	body.append(text);
	detail.replaceChildren(body);
	detail.hidden = false;
}

// Hides edges whose filter is off, and nodes left without a visible edge (result and page movies always stay).
function applyFilters(cy, off) {
	cy.batch(() => {
		cy.elements().removeClass("filtered");
		const hiddenTypes = [...off].flatMap((name) => FILTERS[name] || []);
		cy.edges().filter((edge) => hiddenTypes.includes(edge.data("type"))).addClass("filtered");
		cy.nodes("[focus = 0]").filter((node) => node.connectedEdges().not(".filtered").length === 0).addClass("filtered");
	});
}

async function fetchView(url) {
	const response = await fetch(url, { headers: { Accept: "application/json" } });
	if (!response.ok) {
		throw new Error(`HTTP ${response.status}`);
	}
	return response.json();
}

async function render() {
	if (!container) {
		return;
	}
	let view;
	try {
		view = await fetchView(container.dataset.apiUrl);
	} catch (error) {
		console.warn("graph request failed", error);
		container.textContent = "그래프를 불러오지 못했습니다.";
		return;
	}
	if (view.nodes.length === 0) {
		container.textContent = "그래프에 연결된 노드가 없습니다.";
		return;
	}
	const base = container.dataset.graphUrl || container.dataset.movieUrl;
	renderRelationList(view, base);
	// The text list needs no library; only the canvas does (the CDN may be blocked).
	if (typeof window.cytoscape !== "function") {
		container.textContent = "그래프 라이브러리를 불러오지 못했습니다. 아래 관계 목록에서 같은 관계를 볼 수 있습니다.";
		return;
	}
	const cy = window.cytoscape({
		container,
		elements: [...view.nodes.map((node) => ({ data: nodeData(node) })), ...view.edges.map((edge) => ({ data: edgeData(edge) }))],
		minZoom: 0.2,
		maxZoom: 3,
		style: STYLE,
	});

	// Filters: the page may start with some off (the search graph hides genres, which link nearly every result).
	const off = new Set((container.dataset.hide || "").split(",").map((name) => name.trim()).filter(Boolean));
	// The stop handler is bound before run(), since a non-animated layout stops inside run().
	const relayout = (options, onStop) => {
		const layout = cy.elements().not(".filtered").layout(layoutOptions(cy, options));
		if (onStop) {
			layout.one("layoutstop", onStop);
		}
		layout.run();
	};
	const clearHighlight = () => cy.elements().removeClass("faded highlight");
	const highlight = (node) => {
		const neighborhood = node.closedNeighborhood();
		clearHighlight();
		cy.elements().not(neighborhood).addClass("faded");
		neighborhood.edges().addClass("highlight");
	};
	document.querySelectorAll(".graph-filter").forEach((button) => {
		const name = button.dataset.filter;
		button.setAttribute("aria-pressed", String(!off.has(name)));
		button.addEventListener("click", () => {
			if (off.has(name)) {
				off.delete(name);
			} else {
				off.add(name);
			}
			button.setAttribute("aria-pressed", String(!off.has(name)));
			applyFilters(cy, off);
			relayout({ randomize: false });
		});
	});
	applyFilters(cy, off);
	relayout();

	const actions = {
		// Adds the person's movies that are not on the canvas yet next to the person, then settles the layout.
		async expand(person) {
			let more;
			try {
				more = await fetchView(`${container.dataset.personApiUrl}${encodeURIComponent(person.data("qid"))}`);
			} catch (error) {
				console.warn("person graph request failed", error);
				return null;
			}
			const center = person.position();
			const newNodes = more.nodes.filter((node) => cy.getElementById(node.id).empty());
			cy.add([
				...newNodes.map((node, index) => ({
					data: nodeData({ ...node, focus: false }),
					position: { x: center.x + 80 * Math.cos(index), y: center.y + 80 * Math.sin(index) },
				})),
				...more.edges.filter((edge) => cy.getElementById(`e${edge.id}`).empty()).map((edge) => ({ data: edgeData(edge) })),
			]);
			person.addClass("expanded");
			view = {
				nodes: [...view.nodes, ...newNodes.map((node) => ({ ...node, focus: false }))],
				edges: [...view.edges, ...more.edges.filter((edge) => !view.edges.some((known) => known.id === edge.id))],
			};
			renderRelationList(view, base);
			applyFilters(cy, off);
			const added = newNodes.filter((node) => node.kind === "Movie").length;
			// After the layout settles, keep the person highlighted and zoom to them and their movies.
			relayout({ randomize: false }, () => {
				highlight(person);
				showDetail(person, actions, added);
				cy.animate({ fit: { eles: person.closedNeighborhood().not(".filtered"), padding: 60 }, duration: 400 });
			});
			return added;
		},
	};

	cy.on("tap", "node", (event) => {
		highlight(event.target);
		showDetail(event.target, actions);
	});
	cy.on("tap", (event) => {
		if (event.target === cy) {
			clearHighlight();
			if (detail) {
				detail.hidden = true;
			}
		}
	});
	cy.on("mouseover", "edge", (event) => event.target.addClass("highlight"));
	cy.on("mouseout", "edge", (event) => {
		if (!cy.elements(".faded").length) {
			event.target.removeClass("highlight");
		}
	});
	cy.on("dbltap", "node[kind = 'Movie']", (event) => {
		const tmdbId = event.target.data("tmdbId");
		if (tmdbId != null) {
			window.location.href = `${base}${tmdbId}`;
		}
	});
	window.addEventListener("resize", () => {
		cy.resize();
		cy.fit(cy.elements().not(".filtered"), 30);
	});
}

render();
