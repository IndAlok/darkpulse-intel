import { createContext, useContext } from "react";
import type { Principal } from "../types/api";

export const PrincipalContext = createContext<Principal | null>(null);

export function usePrincipal() {
  return useContext(PrincipalContext);
}
