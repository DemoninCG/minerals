# IMA Mineral Map — frontend

React + Vite + three.js frontend for the [IMA Mineral Map](../README.md). Renders all 6,228 IMA-approved minerals as an interactive 3D point cloud with a relationship inspector for the compositional k-NN graph.

## Data

The app fetches three static JSON files from `public/data/`:

| File | Contents |
|---|---|
| `mineral-map-nodes.json` | One record per mineral: formula, classifications, structure, coordinates, composition profile |
| `mineral-map-neighbors.json` | The exact 10-NN graph with per-component distance decompositions and relationship categories (lazy-loaded) |
| `mineral-map-metadata.json` | Node count, component weights, relationship-category descriptions |

These files are written by `analysis.ipynb` in the repository root — there is no other data source. The neighbors file is ~24 MB, so the first node selection may take a moment while it loads.

## Development

```bash
npm install
npm run sync:data      # optional: re-enrich nodes with Mindat classifications from ../IMA_data_with_mindat.csv
npm run dev            # dev server
npm run build          # type-check + production build to dist/
npm run preview        # serve the production build
```

## Stack

- [React 19](https://react.dev) + [Vite](https://vite.dev)
- [three.js](https://threejs.org) via [@react-three/fiber](https://docs.pmnd.rs/react-three-fiber) and [@react-three/drei](https://github.com/pmndrs/drei) for instanced rendering and controls
- [lucide-react](https://lucide.dev) icons
