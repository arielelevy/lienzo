import { version } from "../../package.json";
import "./ReleaseBadge.css";
import { useUpdateStatus } from "./Updates";

export function ReleaseBadge({ onUpdates, local = false }: { onUpdates?: () => void; local?: boolean }) {
  const { data } = useUpdateStatus("", local);
  return <aside className="release-badge" aria-label="Versión de Lienzo" title={`Lienzo ${version}`}>{onUpdates ? <button onClick={onUpdates} aria-label="Abrir actualizaciones">v{version}</button> : <>v{version}</>}{data?.available && <span className="update-available"> · Actualización disponible</span>}</aside>;
}
