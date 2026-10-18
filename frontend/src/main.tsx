import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { BrandList } from "./components/BrandList";

const container = document.getElementById("brand-list");

if (container) {
  createRoot(container).render(
    <StrictMode>
      <BrandList />
    </StrictMode>,
  );
}
