// Renders /api/discover graph JSON with Cytoscape.js and the fCoSE layout (globals from the CDN).
const container = document.getElementById("graph");

const COLORS = { Movie: "#6750a4", Person: "#e8a33d", Genre: "#2e7d6b", Similar: "#6750a4" };

function toElements(view) {
	const nodes = view.nodes.map((node) => ({
		data: {
			id: node.id,
			kind: node.kind,
			label: node.year ? `${node.name} (${node.year})` : node.name,
			tmdbId: node.tmdbId,
			focus: node.focus ? 1 : 0,
		},
	}));
	const edges = view.edges.map((edge) => ({
		data: {
			id: `e${edge.id}`,
			source: edge.source,
			target: edge.target,
			type: edge.type,
			label: edge.type === "SIMILAR_TO" && edge.score != null ? edge.score.toFixed(2) : "",
		},
	}));
	return [...nodes, ...edges];
}

// fCoSE includes label boxes in the overlap check; plain CoSE is the fallback if the extension did not load.
function layoutOptions() {
	const common = { animate: false, fit: true, padding: 30, nodeDimensionsIncludeLabels: true };
	const edgeLength = (edge) => (edge.data("type") === "SIMILAR_TO" ? 170 : 120);
	if (window.cytoscapeFcose) {
		return {
			...common,
			name: "fcose",
			quality: "proof",
			randomize: true,
			nodeSeparation: 90,
			nodeRepulsion: () => 18000,
			idealEdgeLength: edgeLength,
			edgeElasticity: () => 0.3,
			gravity: 0.15,
			gravityRange: 4,
			numIter: 5000,
			packComponents: true,
			tile: true,
		};
	}
	return { ...common, name: "cose", nodeRepulsion: () => 40000, idealEdgeLength: edgeLength, nodeOverlap: 40 };
}

async function render() {
	if (!container || typeof window.cytoscape !== "function") {
		return;
	}
	const response = await fetch(container.dataset.apiUrl, { headers: { Accept: "application/json" } });
	if (!response.ok) {
		container.textContent = "그래프를 불러오지 못했습니다.";
		return;
	}
	const view = await response.json();
	if (view.nodes.length === 0) {
		container.textContent = "그래프에 연결된 노드가 없습니다.";
		return;
	}
	const cy = window.cytoscape({
		container,
		elements: toElements(view),
		minZoom: 0.2,
		maxZoom: 3,
		style: [
			{
				selector: "node",
				style: {
					label: "data(label)",
					"font-size": 10,
					"text-wrap": "wrap",
					"text-max-width": 110,
					"text-valign": "bottom",
					"text-margin-y": 4,
					"text-background-color": "#ffffff",
					"text-background-opacity": 0.85,
					"text-background-padding": 2,
					"text-background-shape": "roundrectangle",
					"min-zoomed-font-size": 6,
					color: "#1d1b20",
					width: 16,
					height: 16,
				},
			},
			{ selector: 'node[kind = "Movie"]', style: { "background-color": COLORS.Movie, shape: "round-rectangle", width: 20, height: 20 } },
			{ selector: 'node[kind = "Person"]', style: { "background-color": COLORS.Person, "font-size": 9 } },
			{ selector: 'node[kind = "Genre"]', style: { "background-color": COLORS.Genre, shape: "diamond", "font-size": 9 } },
			{ selector: "node[focus = 1]", style: { width: 28, height: 28, "font-size": 12, "font-weight": "bold" } },
			{ selector: "edge", style: { width: 1, "line-color": "#d0ccd6", "curve-style": "bezier", opacity: 0.7 } },
			{ selector: 'edge[type = "DIRECTED"]', style: { "line-color": COLORS.Person, width: 2 } },
			{ selector: 'edge[type = "SIMILAR_TO"]', style: { "line-color": COLORS.Similar, "line-style": "dashed", width: 2 } },
			// Similarity scores appear only on highlighted edges so they do not pile up on the canvas.
			{
				selector: 'edge.highlight[type = "SIMILAR_TO"]',
				style: {
					label: "data(label)",
					"font-size": 9,
					color: COLORS.Similar,
					"text-background-color": "#ffffff",
					"text-background-opacity": 0.9,
					"text-background-padding": 1,
				},
			},
			{ selector: ".faded", style: { opacity: 0.12 } },
			{ selector: "edge.highlight", style: { opacity: 1 } },
		],
	});
	cy.layout(layoutOptions()).run();

	const clearHighlight = () => cy.elements().removeClass("faded highlight");
	cy.on("tap", "node", (event) => {
		const neighborhood = event.target.closedNeighborhood();
		clearHighlight();
		cy.elements().not(neighborhood).addClass("faded");
		neighborhood.edges().addClass("highlight");
	});
	cy.on("tap", (event) => {
		if (event.target === cy) {
			clearHighlight();
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
		const base = container.dataset.graphUrl || container.dataset.movieUrl;
		if (tmdbId != null) {
			window.location.href = `${base}${tmdbId}`;
		}
	});
	window.addEventListener("resize", () => {
		cy.resize();
		cy.fit(undefined, 30);
	});
}

render();
