const express = require("express");
const app = express();
const PORT = process.env.PORT || 8080;

app.use(express.json());

const items = [
  { id: 1, name: "item-1", value: "alpha" },
  { id: 2, name: "item-2", value: "beta" },
  { id: 3, name: "item-3", value: "gamma" },
];

app.get("/", (req, res) => {
  res.json({ message: "AKS Backend Service", timestamp: new Date().toISOString() });
});

app.get("/health", (req, res) => {
  res.status(200).json({ status: "healthy" });
});

app.get("/api/items", (req, res) => {
  res.json(items);
});

app.get("/api/items/:id", (req, res) => {
  const item = items.find((i) => i.id === parseInt(req.params.id));
  if (!item) return res.status(404).json({ error: "Not found" });
  res.json(item);
});

app.post("/api/items", (req, res) => {
  const newItem = { id: items.length + 1, ...req.body };
  items.push(newItem);
  res.status(201).json(newItem);
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
