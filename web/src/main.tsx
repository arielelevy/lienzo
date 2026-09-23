import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { Docs } from "./components/Docs";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* /docs es la referencia: misma pagina y mismo bundle, otra pantalla */}
    {window.location.pathname.replace(/\/+$/, "") === "/docs" ? <Docs /> : <App />}
  </React.StrictMode>,
);
