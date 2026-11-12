import { setupServer } from "msw/node";
import { handlers } from "@/mocks/handlers";

/** The same handlers the browser worker serves, in node. One mock, two transports. */
export const server = setupServer(...handlers);
