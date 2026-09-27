# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: code-builder-v2-autonomous.spec.js >> Code Builder V2 Autonomous Production Test >> complete autonomous build: plan -> execute -> verify -> preview
- Location: e2e/code-builder-v2-autonomous.spec.js:131:3

# Error details

```
TimeoutError: page.waitForResponse: Timeout 30000ms exceeded while waiting for event "response"
```

# Page snapshot

```yaml
- generic [active] [ref=f4e1]: "{\"detail\":{\"code\":\"http_404\",\"message\":\"Not Found\",\"technical_details\":{\"method\":\"GET\",\"path\":\"/api/code-builder-v2/tasks/6cc027df-e64b-4f81-a632-3a3c3bece702/preview/index.html\",\"query\":\"\"},\"exception_type\":\"HTTPException\"},\"ok\":false,\"code\":\"http_404\",\"message\":\"Not Found\",\"http_status\":404,\"technical_details\":{\"method\":\"GET\",\"path\":\"/api/code-builder-v2/tasks/6cc027df-e64b-4f81-a632-3a3c3bece702/preview/index.html\",\"query\":\"\",\"exception_type\":\"HTTPException\"}}"
```

# Test source

```ts
  123 |           page.locator('.lumina-document'),
  124 |         ],
  125 |       }).catch(() => undefined);
  126 |     }
  127 |     await attachDiagnostics(testInfo, testInfo.diagnostics);
  128 |     expect(testInfo.diagnostics.pageErrors, 'Uncaught browser errors').toEqual([]);
  129 |   });
  130 | 
  131 |   test('complete autonomous build: plan -> execute -> verify -> preview', async ({ page }, testInfo) => {
  132 |     await ensureSignedIn(page);
  133 | 
  134 |     // Navigate to Code Builder V2
  135 |     await page.goto('/studio/code-builder-v2');
  136 |     await expect(page.getByRole('heading', { name: 'Code Builder V2' })).toBeVisible({ timeout: 30000 });
  137 | 
  138 |     // Fill in the prompt
  139 |     const promptTextarea = page.locator('textarea').first();
  140 |     await expect(promptTextarea).toBeVisible();
  141 |     await promptTextarea.fill(SIMPLE_APP_PROMPT);
  142 | 
  143 |     // Fill in model if input exists
  144 |     const modelInput = page.locator('input[name="model"], input[placeholder*="model" i]').first();
  145 |     if (await modelInput.isVisible().catch(() => false)) {
  146 |       await modelInput.fill(E2E_MODEL);
  147 |     }
  148 | 
  149 |     // Submit: Create Plan
  150 |     const createTaskResponse = page.waitForResponse((response) => (
  151 |       new URL(response.url()).pathname === '/api/code-builder-v2/tasks' && response.request().method() === 'POST'
  152 |     ), { timeout: 30000 });
  153 | 
  154 |     await page.getByRole('button', { name: 'Create autonomous plan' }).click();
  155 |     const createResponse = await createTaskResponse;
  156 |     expect(createResponse.status()).toBe(200);
  157 |     const taskPayload = await createResponse.json();
  158 |     const taskId = taskPayload.id;
  159 |     expect(typeof taskId).toBe('string');
  160 |     testInfo.annotations.push({ type: 'task-id', description: taskId });
  161 | 
  162 |     // Wait for plan to be ready (awaiting_approval)
  163 |     let task = await pollTask(page, taskId, ['awaiting_approval', 'failed', 'cancelled'], 180000);
  164 | 
  165 |     if (task.status === 'failed') {
  166 |       throw new Error(`Code Builder V2 plan failed: ${task.error || 'no error payload'}`);
  167 |     }
  168 |     if (task.status === 'cancelled') {
  169 |       throw new Error('Task was cancelled unexpectedly');
  170 |     }
  171 | 
  172 |     expect(task.status).toBe('awaiting_approval');
  173 |     expect(task.plan).toBeTruthy();
  174 |     expect(task.plan.summary.trim().length).toBeGreaterThan(0);
  175 |     expect(Array.isArray(task.plan.changes)).toBe(true);
  176 |     expect(task.plan.changes.length).toBeGreaterThan(0);
  177 |     expect(task.plan.changes.some(c => c.path && typeof c.path === 'string')).toBe(true);
  178 | 
  179 |     // Verify plan contains only index.html
  180 |     const plannedPaths = task.plan.changes.map(c => c.path);
  181 |     expect(plannedPaths).toEqual(['index.html']);
  182 |     expect(task.plan.changes[0].operation).toBe('create');
  183 | 
  184 |     // Execute the plan (Approve/Execute)
  185 |     const executeResponse = page.waitForResponse((response) => (
  186 |       new URL(response.url()).pathname === `/api/code-builder-v2/tasks/${taskId}/execute` && response.request().method() === 'POST'
  187 |     ), { timeout: 30000 });
  188 | 
  189 |     await expect(page.getByRole('button', { name: 'Execute' })).toBeEnabled({ timeout: 30000 });
  190 |     await page.getByRole('button', { name: 'Execute' }).click();
  191 |     const execResponse = await executeResponse;
  192 |     expect(execResponse.status()).toBe(200);
  193 | 
  194 |     // Wait for execution to complete
  195 |     task = await pollExecution(page, taskId, 600000);
  196 | 
  197 |     // Verify execution completed successfully
  198 |     expect(task.status).toBe('completed');
  199 |     expect(task.execution).toBeTruthy();
  200 |     expect(task.execution.changed_paths).toContain('index.html');
  201 |     expect(task.execution.validation_commands).toBeDefined();
  202 | 
  203 |     // Verify no Ollama/localhost references
  204 |     const serialized = JSON.stringify(task);
  205 |     expect(serialized).not.toMatch(/ollama|127\.0\.0\.1:11434/i);
  206 | 
  207 |     // Capture execution details
  208 |     await testInfo.attach('execution-result', {
  209 |       contentType: 'application/json',
  210 |       body: JSON.stringify({
  211 |         taskId,
  212 |         status: task.status,
  213 |         changedPaths: task.execution.changed_paths,
  214 |         validationResults: task.execution.validation_commands,
  215 |         timestamp: new Date().toISOString(),
  216 |       }, null, 2),
  217 |     });
  218 | 
  219 |     // Navigate to preview the generated app
  220 |     // The preview should be available at a known route
  221 |     const previewUrl = `/api/code-builder-v2/tasks/${taskId}/preview/index.html`;
  222 |     
> 223 |     const previewResponse = page.waitForResponse((response) => (
      |                                  ^ TimeoutError: page.waitForResponse: Timeout 30000ms exceeded while waiting for event "response"
  224 |       response.url().includes(`/api/code-builder-v2/tasks/${taskId}/preview/`) && response.status() === 200
  225 |     ), { timeout: 30000 });
  226 | 
  227 |     // Try to access preview via the preview endpoint
  228 |     await page.goto(previewUrl, { waitUntil: 'networkidle', timeout: 30000 });
  229 |     const previewResp = await previewResponse;
  230 |     expect(previewResp.status()).toBe(200);
  231 | 
  232 |     // Verify the preview loads correctly
  233 |     await expect(page.locator('body')).toBeVisible({ timeout: 15000 });
  234 | 
  235 |     // Check for counter app elements
  236 |     await expect(page.locator('#count, #counter, [id*="count" i]')).toBeVisible({ timeout: 15000 });
  237 |     
  238 |     // Find increment button
  239 |     const incrementBtn = page.locator('button#incrementBtn, button:has-text("Increment"), button:has-text("+"), button:has-text("increment" i)').first();
  240 |     await expect(incrementBtn).toBeVisible({ timeout: 15000 });
  241 | 
  242 |     // Find decrement button
  243 |     const decrementBtn = page.locator('button#decrementBtn, button:has-text("Decrement"), button:has-text("-"), button:has-text("decrement" i)').first();
  244 |     await expect(decrementBtn).toBeVisible({ timeout: 15000 });
  245 | 
  246 |     // Find reset button
  247 |     const resetBtn = page.locator('button#resetBtn, button:has-text("Reset"), button:has-text("reset" i)').first();
  248 |     await expect(resetBtn).toBeVisible({ timeout: 15000 });
  249 | 
  250 |     // Test user flow: Increment
  251 |     const initialCount = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
  252 |     log(`Initial count: ${initialCount}`);
  253 | 
  254 |     await incrementBtn.click();
  255 |     await page.waitForTimeout(500);
  256 |     
  257 |     const afterIncrement = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
  258 |     log(`After increment: ${afterIncrement}`);
  259 | 
  260 |     // Test user flow: Decrement
  261 |     await decrementBtn.click();
  262 |     await page.waitForTimeout(500);
  263 |     
  264 |     const afterDecrement = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
  265 |     log(`After decrement: ${afterDecrement}`);
  266 | 
  267 |     // Test user flow: Reset
  268 |     await resetBtn.click();
  269 |     await page.waitForTimeout(500);
  270 |     
  271 |     const afterReset = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
  272 |     log(`After reset: ${afterReset}`);
  273 | 
  274 |     // Verify localStorage persistence
  275 |     const localStorageCount = await page.evaluate(() => localStorage.getItem('count') || localStorage.getItem('counter') || '0');
  276 |     log(`localStorage count: ${localStorageCount}`);
  277 | 
  278 |     // Test reload persists state
  279 |     await page.reload({ waitUntil: 'networkidle' });
  280 |     await expect(page.locator('body')).toBeVisible({ timeout: 15000 });
  281 |     
  282 |     const afterReload = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
  283 |     log(`After reload: ${afterReload}`);
  284 | 
  285 |     // Capture final diagnostics
  286 |     await testInfo.attach('preview-verification', {
  287 |       contentType: 'application/json',
  288 |       body: JSON.stringify({
  289 |         initialCount,
  290 |         afterIncrement,
  291 |         afterDecrement,
  292 |         afterReset,
  293 |         localStorageCount,
  294 |         afterReload,
  295 |         passed: true,
  296 |       }, null, 2),
  297 |     });
  298 |   });
  299 | 
  300 |   test('code builder execution failure diagnostics', async ({ page }, testInfo) => {
  301 |     await ensureSignedIn(page);
  302 | 
  303 |     await page.goto('/studio/code-builder-v2');
  304 |     await expect(page.getByRole('heading', { name: 'Code Builder V2' })).toBeVisible({ timeout: 30000 });
  305 | 
  306 |     // Submit an impossible prompt that should fail validation
  307 |     const badPrompt = `Create an app that connects to a non-existent database and requires valid SSL certificates that don't exist.
  308 | The plan must reference files that cannot be created and validation commands that will fail.`;
  309 | 
  310 |     const promptTextarea = page.locator('textarea').first();
  311 |     await promptTextarea.fill(badPrompt);
  312 | 
  313 |     const modelInput = page.locator('input[name="model"], input[placeholder*="model" i]').first();
  314 |     if (await modelInput.isVisible().catch(() => false)) {
  315 |       await modelInput.fill(E2E_MODEL);
  316 |     }
  317 | 
  318 |     const createTaskResponse = page.waitForResponse((response) => (
  319 |       new URL(response.url()).pathname === '/api/code-builder-v2/tasks' && response.request().method() === 'POST'
  320 |     ), { timeout: 30000 });
  321 | 
  322 |     await page.getByRole('button', { name: 'Create autonomous plan' }).click();
  323 |     const createResponse = await createTaskResponse;
```