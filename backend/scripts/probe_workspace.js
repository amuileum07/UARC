(async () => {
  const deadline = performance.now() + 45000;
  while (!window.__uarcWorkspaceCheck) {
    if (performance.now() > deadline) throw Error("Workspace probe did not load");
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return await window.__uarcWorkspaceCheck;
})()
