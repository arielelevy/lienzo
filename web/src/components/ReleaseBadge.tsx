import { version } from "../../package.json";
import "./ReleaseBadge.css";

export function ReleaseBadge() {
  return <aside className="release-badge" aria-label="Versión de Lienzo" title={`Lienzo ${version}`}>v{version}</aside>;
}
