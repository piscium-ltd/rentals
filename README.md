# Rentals – Powered by iNova4.0

**iNova4.0** is not just an ERP – it's a digital ecosystem transforming Kenya’s rental and property development economy. Built as a cloud-native, API-first platform, it enables landlords, tenants, financial institutions, and regulators to collaborate seamlessly for greater efficiency, transparency, and financial inclusion.

This repository contains the **Rentals App**, the core module of the iNova4.0 platform. It integrates tightly with Family Bank’s infrastructure and is tailored to support landlords, tenants, and financial administrators with features like automated rent collection, tax compliance, lease management, embedded finance, and ESG reporting.

---

## 🚀 Features

### 🔄 End-to-End Automation

- **Automated Rent Collection & Reconciliation** via mobile money, PESALink, RTGS, and card gateways. Reconciliations are handled automatically through Family Bank's systems.

### 📄 Digital Lease Management

- Create, sign, and store digital leases with built-in verification using registry APIs for fraud reduction and compliance.

### 📊 Real-Time Financial Tracking

- Built-in IFRS for SMEs-compliant ledgers simplify reporting and creditworthiness assessment.

### 🧾 Tax Compliance

- Seamless MRI tax computation and filing via **KRA eRITS** integration.

### 💳 Embedded Finance

- Rent-backed loans, milestone-based development loans, and insurance, powered by verified financial data from Family Bank.

### 📉 Precision Lending Engine

- Data-driven risk scoring for landlords and developers based on verified tenant payment behavior.

### 🧑‍💻 Self-Service Dashboards

- Tenants can manage payments and maintenance; landlords get live portfolio, occupancy, and financial insights.

### 🌍 ESG & CSR Integration

- Tracks affordable housing, energy efficiency, and provides in-app financial training for property owners.

---

## 🧩 Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

````bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app rentals

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/rentals
pre-commit install
````

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
