import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

// StrictMode keeps development-only lifecycle checks enabled; production still
// mounts the same single application root.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
