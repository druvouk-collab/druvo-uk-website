<!-- Owner-supplied master roadmap (24 Nov 2026). This is the governing plan; progress is tracked in docs/PROGRESS.md. -->

# DRUVO — Master Development Roadmap and Operational Requirements

## 1. Our original vision

Before continuing development, I want to clarify the complete vision for DRUVO.

DRUVO is not simply an e-commerce website. Our primary objective is to build our own fully operational, cloud-based, multichannel e-commerce management software called **DRUVO Manager**.

The software must centrally manage the following five selling platforms:

- DRUVO.uk
- eBay
- Amazon
- Vinted
- Depop

Our objective is to upload a product once through DRUVO Manager and automatically publish, manage and synchronise it across all supported selling platforms.

I want you to follow this master roadmap in order.

## Phase 1 — Review and consolidate existing development

Before building anything else:

- Review the original DRUVO Manager source code.
- Review the existing DRUVO website source code.
- Review all GitHub repositories and development branches.
- Identify all completed, partially completed and non-functional features.
- Verify the existing eBay and Amazon integrations.
- Review the previous difficulties with Vinted API access.
- Identify the requirements for Depop integration.
- Review the newly developed website checkout, admin dashboard and security features.
- Identify duplicated functionality between the website admin dashboard and DRUVO Manager.

Do not unnecessarily rebuild working functionality.

DRUVO Manager must remain our central management system, and the website must operate as one of its selling channels.

## Phase 2 — Central cloud infrastructure

Build or consolidate a reliable central cloud database that manages:

- Products and unique SKUs.
- Product photographs.
- Categories, brands, sizes and conditions.
- Purchase costs and selling prices.
- Available and reserved stock.
- Marketplace listing IDs.
- Customer orders.
- Payments and refunds.
- Shipping and tracking.
- Marketplace fees.
- Business expenses.
- Sales and profit.

The complete system must operate 24/7 without requiring my MacBook to remain switched on.

It must be accessible securely from my mobile phone, tablet and computer.

## Phase 3 — Universal product listing system

I want to create a product only once inside DRUVO Manager.

The product creation page should allow me to enter:

- Product name.
- Brand.
- Category.
- Description.
- Size and colour.
- Condition.
- Purchase price.
- Selling price.
- Available quantity.
- Product photographs.
- Delivery information.
- SKU and barcode, where applicable.

I should then be able to select which platforms I want to publish the product on.

The software should automatically adapt the listing to each marketplace's requirements, including categories, image specifications and mandatory product information.

Allow different selling prices for different platforms because marketplace fees vary.

The system must clearly display whether each listing is published, pending, failed, sold or requires manual attention.

## Phase 4 — Marketplace integrations

### DRUVO.uk

Complete the connection between our website and DRUVO Manager.

Ensure the following work:

- Automatic product publishing.
- Stock and price synchronisation.
- Customer checkout.
- Stripe payments.
- Apple Pay and Google Pay.
- PayPal, subject to availability and approval.
- Automatic order confirmation.
- Dispatch and tracking emails.
- Refunds and cancellations.
- Discount codes.

The website must obtain its stock information from the central system.

### eBay

Review and complete the existing integration.

Ensure the software can:

- Create listings.
- Update listings.
- Change prices.
- Update quantities.
- End listings.
- Import orders.
- Record marketplace fees.
- Submit tracking information.
- Synchronise sales and inventory.

Test all supported operations rather than assuming the existing connection works.

### Amazon

Review the existing Amazon integration and verify its functionality.

Complete supported listing, inventory, pricing, order, fee and shipping operations using Amazon's approved APIs.

Clearly identify any seller account permissions, product restrictions or approval requirements.

### Vinted

We previously experienced difficulties connecting Vinted because of API restrictions.

Investigate all legitimate integration options, including official APIs, approved partners and authorised business integrations.

Do not use prohibited automation, bypass security restrictions or implement anything that could result in our Vinted account being suspended.

If full automation is unavailable, develop the best compliant assisted workflow, including listing preparation, manual publishing assistance and stock reconciliation.

Clearly distinguish automatic features from manual ones.

### Depop

Investigate Depop's official API availability, partner integrations and seller permissions.

Implement the maximum permitted functionality.

If full automation is unavailable, develop a compliant assisted workflow similar to Vinted.

Our objective remains to manage all five platforms from DRUVO Manager as far as their rules and technical capabilities allow.

## Phase 5 — Intelligent stock management

This is one of the most important requirements.

If I have one pair of trainers available and publish it across five platforms, the software must recognise that there is only one physical item in stock.

When that item sells:

1. Import the order.
2. Update the central stock immediately.
3. Remove or update the corresponding listings on other connected platforms.
4. Prevent additional website purchases.
5. Notify me of the sale.
6. Record the transaction and expected profit.

Implement:

- Real-time updates where supported.
- Webhooks and scheduled reconciliation.
- Duplicate order prevention.
- Stock reservation during website checkout.
- Automatic retry mechanisms.
- Low-stock notifications.
- Failed synchronisation alerts.
- Overselling detection and conflict resolution.
- Complete stock movement history.

Do not claim that cross-platform overselling is impossible where external marketplaces introduce delays. Implement the strongest practical safeguards.

## Phase 6 — Central order management

I want one dashboard where I can see every order from every connected platform.

Each order should display:

- Selling platform.
- Order number.
- Product details.
- Customer information where permitted.
- Selling price.
- Marketplace fees.
- Payment status.
- Dispatch deadline.
- Shipping address.
- Tracking number.
- Order status.
- Actual or estimated profit.

Allow me to manage packing, dispatch, tracking, cancellations, returns and refunds centrally wherever the marketplace supports these operations.

Investigate approved integrations with Royal Mail, Evri, DPD and other suitable UK delivery companies.

## Phase 7 — Financial management

Build a complete financial dashboard showing:

- Today's sales.
- Weekly sales.
- Monthly sales.
- Annual sales.
- Revenue by platform.
- Product purchase costs.
- Marketplace commissions.
- Payment processing fees.
- Delivery and packaging costs.
- Refunds.
- Business expenses.
- Gross and net operating profit.
- Inventory value.
- Best-selling products.
- Most profitable selling platforms.

Distinguish estimated fees and profit from confirmed actual figures.

Include downloadable reports suitable for accounting and tax preparation.

## Phase 8 — AI-powered business assistance

Once the core system is fully functional, introduce useful AI features:

- Generate professional product titles.
- Generate product descriptions.
- Improve product photographs.
- Suggest relevant categories.
- Suggest competitive selling prices using permitted data sources.
- Identify potentially profitable products.
- Identify slow-selling stock.
- Recommend price reductions.
- Generate business performance summaries.
- Improve website SEO.

AI-generated information must remain editable and must not invent product specifications or condition details.

## Phase 9 — Marketing and business growth

Improve DRUVO.uk through:

- Google Search Console.
- Google Merchant Center.
- Google Shopping.
- Google Images.
- Facebook and Instagram product catalogues.
- Search engine optimisation.
- Promotional campaigns.
- Discount codes.
- Customer email marketing with appropriate consent.
- Abandoned basket recovery where legally permitted.
- Customer reviews.

Prioritise free and low-cost marketing options initially.

Do not purchase advertising or paid subscriptions without my approval.

## Phase 10 — Mobile-friendly management dashboard

Create a professional, easy-to-use dashboard containing:

- Business overview.
- Products.
- Add new product.
- Marketplace listings.
- Inventory.
- Orders.
- Dispatch.
- Returns and refunds.
- Customers.
- Sales and profit.
- Expenses.
- Reports.
- Marketplace connections.
- Notifications.
- Settings.

I should be able to photograph a product using my phone, create a listing and publish it to supported marketplaces without using my computer.

## Phase 11 — Security and reliability

Preserve and improve the security features already developed.

Ensure the system includes:

- Secure administrator authentication.
- Two-factor authentication.
- Secure API credential storage.
- Automatic encrypted backups.
- Tested backup restoration.
- Error monitoring.
- Activity and audit logs.
- Automatic integration failure alerts.
- GDPR compliance.
- Appropriate customer data retention.
- Protection against unauthorised access.
- Reliable background processing.
- Automatic recovery from temporary service failures.

Keep sensitive information out of GitHub and public source code.

## Phase 12 — Complete operational testing

Before declaring the software operational, conduct comprehensive end-to-end testing.

Test:

- Creating a product.
- Publishing it to each supported marketplace.
- Editing prices and descriptions.
- Updating stock.
- Receiving marketplace orders.
- Website payments.
- Failed payments.
- Simultaneous purchases.
- Automatic stock synchronisation.
- Ending marketplace listings.
- Dispatch and tracking.
- Returns and refunds.
- Profit calculations.
- Automatic emails.
- Mobile functionality.
- Database backup and recovery.
- Marketplace API failures.
- Operation without my MacBook.

Use staging environments and test accounts wherever available.

Clearly distinguish automated code tests, sandbox integration tests and verified live functionality.

Do not make real purchases, publish test listings publicly or activate paid services without my approval.

## Phase 13 — Production launch

Once the system has been tested and approved:

- Deploy the complete system to reliable cloud hosting.
- Connect all approved production integrations.
- Connect the live DRUVO website.
- Configure automatic background processing.
- Configure backups and monitoring.
- Verify mobile access.
- Prepare a complete user guide.
- Prepare a technical handover document.
- Provide a recovery and maintenance guide.

## Development instructions

From now on:

1. Follow this roadmap in the correct order.
2. Preserve all existing working functionality.
3. Do not create unnecessary separate management systems.
4. Maintain one central source of truth for inventory.
5. Work on development branches before changing production.
6. Test every completed feature.
7. Keep the roadmap updated with actual progress.
8. Clearly explain any technical or marketplace restrictions.
9. Ask me only when account access, credentials, permissions, payments or important decisions are required.
10. Continue with all independent development tasks that are not blocked.
11. Do not mark any feature as operational until it has been appropriately tested.
12. Prioritise free and affordable infrastructure without compromising reliability.

Maintain a master progress document showing every feature as:

- Not started.
- In development.
- Built but untested.
- Tested in staging.
- Verified in production.
- Blocked by external requirements.

## Final objective

I want DRUVO Manager to become our own professional multichannel e-commerce management software, similar in purpose to Linnworks, but designed specifically for our business.

I do not want just a demonstration, prototype or collection of disconnected features.

I want a fully working, secure, reliable and operational business management system that allows me to run DRUVO from one dashboard.

Please begin by reviewing everything we have already built against this roadmap.

Provide me with:

- Our actual current development status.
- What has already been completed.
- What needs to be improved.
- What remains to be built.
- What is blocked.
- What you need from me.
- Expected development stages.
- Estimated monthly operating costs.

After completing the review, begin implementing the remaining work in priority order without unnecessarily rebuilding existing features.

This document is now our master DRUVO development roadmap.

### Our priorities

1

Unify our existing software and website

Immediate priority

2

Complete website, eBay and Amazon integrations

Core operations

3

Resolve Vinted and Depop integrations

Marketplace expansion

4

Automate inventory, orders and finances

Business automation

5

Complete testing and cloud deployment

Production launch

6

AI features, marketing and business growth

Expansion

The most important thing is that Claude understands DRUVO Manager is our main product, and DRUVO.uk is just one of its selling channels.
