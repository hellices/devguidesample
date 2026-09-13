const vocabulary = {tag: ["design", "build", "operate", "identity"], service: ["one", "two"], technology: ["python", "kubernetes"]};

function element(extra = {}) {
  return {
    hidden: false, textContent: "", value: "", checked: false, dataset: {},
    listeners: {}, addEventListener(type, callback) { this.listeners[type] = callback; },
    ...extra,
  };
}

function fixture(query = "", catalog) {
  const controls = (catalog?.controls || Object.entries(vocabulary).flatMap(([name, values]) =>
    values.map(value => ({name, value, label: value}))
  )).map(({name, value, label}) => element({name, value, labels: [{textContent: label}]}));
  const topics = catalog?.topics || [
    [
      {tags: '["design"]', services: '["one"]', technologies: '["python"]', search: "Agent entry"},
      {tags: '["design","build"]', services: '["one"]', technologies: '["python"]', search: "Agent Memory"},
    ],
    [{tags: '["build"]', services: '["two"]', technologies: '["kubernetes"]', search: "Other"}],
  ];
  const rows = [];
  const cards = topics.map(topic => {
    const members = topic.map(dataset => element({dataset}));
    rows.push(...members);
    const count = element();
    return element({querySelectorAll: () => members, querySelector: () => count});
  });
  const nodes = Object.fromEntries(["form", "count", "summary", "alert", "empty"].map(key => [`[data-explore-${key}]`, element()]));
  const search = element({name: "text"});
  const root = element({
    querySelector: selector => selector === '[name="text"]' ? search : nodes[selector],
    querySelectorAll: selector => selector === 'input[type="checkbox"]' ? controls : cards,
  });
  const urls = [];
  const listeners = {};
  const env = {
    location: new URL(`https://example.test/project/explore/${query}`),
    history: {replaceState: (_, __, url) => {
      urls.push(url);
      env.location = new URL(url, env.location.href);
    }},
    addEventListener(type, callback) { listeners[type] = callback; },
  };
  return {root, env, urls, listeners, nodes, controls, rows, cards, search, form: nodes["[data-explore-form]"]};
}

module.exports = {fixture, vocabulary};
