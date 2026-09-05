import { useCallback, useState } from "react";

/** Booleano recordado en localStorage ("1"/"0"). Sin storage, vive solo en memoria. */
export function useLocalFlag(key: string, initial: boolean): [boolean, () => void, (v: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const s = localStorage.getItem(key);
      return s === null ? initial : s === "1";
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (v: boolean) => {
      setValue(v);
      try {
        localStorage.setItem(key, v ? "1" : "0");
      } catch {
        /* sin storage, no importa */
      }
    },
    [key],
  );
  const toggle = useCallback(() => set(!value), [set, value]);
  return [value, toggle, set];
}
