import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Login from "../src/pages/Login";
import { mkUser, mockApi, renderApp } from "./helpers";

const tree = <Routes><Route path="/login" element={<Login />} /><Route path="/" element={<div>HOME</div>} /><Route path="/profile" element={<div>PROFILE</div>} /></Routes>;
const ok = (u = mkUser()) => ({ access_token: "t", token_type: "bearer", expires_in: 900, csrf_token: "c", user: u });

describe("Login", () => {
  it("validates required fields without calling the API", async () => {
    const api = mockApi({});
    renderApp(tree, "/login");
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your username or email")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
  });

  it("signs in and navigates home", async () => {
    const api = mockApi({ "POST /auth/login": ok() });
    renderApp(tree, "/login");
    await userEvent.type(await screen.findByLabelText("Username or email"), "alice");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("HOME")).toBeInTheDocument();
    expect(api.calls[0].body).toEqual({ identifier: "alice", password: "pw" });
  });

  it("shows a uniform message for bad credentials", async () => {
    mockApi({ "POST /auth/login": () => ({ status: 401, body: { error: { code: "unauthorized", message: "x" } } }) });
    renderApp(tree, "/login");
    await userEvent.type(await screen.findByLabelText("Username or email"), "alice");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials.");
  });

  it("explains rate limiting", async () => {
    mockApi({ "POST /auth/login": () => ({ status: 429, body: { error: { code: "rate_limited", message: "x" } } }) });
    renderApp(tree, "/login");
    await userEvent.type(await screen.findByLabelText("Username or email"), "a");
    await userEvent.type(screen.getByLabelText("Password"), "b");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/too many attempts/i);
  });

  it("forces a password change when required", async () => {
    mockApi({ "POST /auth/login": ok(mkUser(["ADMIN"], { must_change_password: true })) });
    renderApp(tree, "/login");
    await userEvent.type(await screen.findByLabelText("Username or email"), "alice");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByText("PROFILE")).toBeInTheDocument());
  });
});
