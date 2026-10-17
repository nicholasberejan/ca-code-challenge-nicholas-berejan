import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

const container = document.getElementById("brand-list");

if (container) {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
