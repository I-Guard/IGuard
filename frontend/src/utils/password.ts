import { z } from "zod";

/** Mirrors the backend policy (server remains authoritative). */
export const passwordSchema = z.string().min(12, "At least 12 characters").max(256)
  .regex(/[a-z]/, "Needs a lowercase letter").regex(/[A-Z]/, "Needs an uppercase letter").regex(/\d/, "Needs a digit");
