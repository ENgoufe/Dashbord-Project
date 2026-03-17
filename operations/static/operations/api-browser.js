document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("[data-api-browser]");
    if (!root) {
        return;
    }

    const apiUrl = root.dataset.apiUrl;
    const filterName = root.dataset.filterName;
    const pageType = root.dataset.pageType || "";
    const columns = (root.dataset.columns || "").split(",").filter(Boolean);
    const sortTypes = (root.dataset.sortTypes || "").split(",");
    const form = root.querySelector("[data-filter-form]");
    const countNode = root.querySelector("[data-result-count]");
    const resultsBody = root.querySelector("[data-results-body]");
    const emptyState = root.querySelector("[data-empty-state]");
    const errorState = root.querySelector("[data-error-state]");
    const searchInput = root.querySelector("[data-search-input]");
    const resetTableButton = root.querySelector("[data-reset-table]");
    const sortButtons = Array.from(root.querySelectorAll("[data-sort-key]"));
    let allItems = [];
    let sortState = { key: "", direction: "asc" };

    function createCell(value) {
        const cell = document.createElement("td");
        cell.textContent = value ?? "";
        return cell;
    }

    function createStatusBadge(status) {
        const badge = document.createElement("span");
        badge.className = `status-badge status-${status}`;
        badge.textContent = status ?? "";
        return badge;
    }

    function normalizeValue(value, type) {
        if (type === "number") {
            const numeric = Number(value);
            return Number.isNaN(numeric) ? Number.NEGATIVE_INFINITY : numeric;
        }

        if (type === "date") {
            const parsed = Date.parse(value);
            return Number.isNaN(parsed) ? 0 : parsed;
        }

        return String(value ?? "").toLowerCase();
    }

    function getSortType(key) {
        const index = columns.indexOf(key);
        return sortTypes[index] || "text";
    }

    function applyTableState(items) {
        const query = (searchInput?.value || "").trim().toLowerCase();
        let filteredItems = items;

        if (query) {
            filteredItems = filteredItems.filter((item) =>
                columns.some((column) =>
                    String(item[column] ?? "").toLowerCase().includes(query)
                )
            );
        }

        if (sortState.key) {
            const sortType = getSortType(sortState.key);
            filteredItems = [...filteredItems].sort((left, right) => {
                const leftValue = normalizeValue(left[sortState.key], sortType);
                const rightValue = normalizeValue(right[sortState.key], sortType);

                if (leftValue < rightValue) {
                    return sortState.direction === "asc" ? -1 : 1;
                }

                if (leftValue > rightValue) {
                    return sortState.direction === "asc" ? 1 : -1;
                }

                return 0;
            });
        }

        return filteredItems;
    }

    function renderOrderRows(items) {
        resultsBody.innerHTML = "";
        items.forEach((item) => {
            const row = document.createElement("tr");
            row.appendChild(createCell(item.order_number));
            row.appendChild(createCell(item.product_sku));
            row.appendChild(createCell(item.product_name));
            row.appendChild(createCell(item.quantity));
            row.appendChild(createCell(item.due_date));

            const statusCell = document.createElement("td");
            statusCell.appendChild(createStatusBadge(item.status));
            row.appendChild(statusCell);

            resultsBody.appendChild(row);
        });
    }

    function renderDefaultRows(items) {
        resultsBody.innerHTML = "";
        items.forEach((item) => {
            const row = document.createElement("tr");
            columns.forEach((column) => {
                row.appendChild(createCell(item[column]));
            });
            resultsBody.appendChild(row);
        });
    }

    function renderRows(items) {
        if (pageType === "orders") {
            renderOrderRows(items);
            return;
        }

        renderDefaultRows(items);
    }

    function renderCurrentItems() {
        const visibleItems = applyTableState(allItems);
        countNode.textContent = `${visibleItems.length} Eintraege`;
        renderRows(visibleItems);
        emptyState.hidden = visibleItems.length > 0;
        if (visibleItems.length === 0) {
            emptyState.textContent = "Keine Daten fuer den aktuellen Filter gefunden.";
        }
    }

    async function loadData() {
        const params = new URLSearchParams();
        const filterValue = form.elements[filterName].value.trim();
        if (filterValue) {
            params.set(filterName, filterValue);
        }

        const requestUrl = params.toString() ? `${apiUrl}?${params}` : apiUrl;

        emptyState.hidden = true;
        errorState.hidden = true;

        try {
            const response = await fetch(requestUrl, {
                headers: { Accept: "application/json" },
            });

            if (!response.ok) {
                throw new Error(`API antwortet mit Status ${response.status}.`);
            }

            const payload = await response.json();
            allItems = payload.results || [];
            renderCurrentItems();
        } catch (error) {
            resultsBody.innerHTML = "";
            allItems = [];
            countNode.textContent = "0 Eintraege";
            emptyState.hidden = true;
            errorState.hidden = false;
            errorState.textContent = error.message;
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        loadData();
    });

    searchInput?.addEventListener("input", () => {
        renderCurrentItems();
    });

    resetTableButton?.addEventListener("click", () => {
        if (searchInput) {
            searchInput.value = "";
        }
        sortState = { key: "", direction: "asc" };
        renderCurrentItems();
    });

    sortButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const key = button.dataset.sortKey;
            if (!key) {
                return;
            }

            if (sortState.key === key) {
                sortState.direction = sortState.direction === "asc" ? "desc" : "asc";
            } else {
                sortState = { key, direction: "asc" };
            }

            renderCurrentItems();
        });
    });

    loadData();
});
