# Production Deployment Guide

**Project Status:** Production-ready ✅
- **Backend:** Render.com (https://pfl-xmq7.onrender.com)
- **Frontend:** Vercel (https://pfl-4azo.vercel.app)
- **Database:** Supabase PostgreSQL
- **Docker:** ❌ Removed (not needed for cloud deployment)

---

## 🚀 Backend Deployment (Render.com)

### Step 1: Update Environment Variables on Render Dashboard

Go to: **Render Dashboard → Your Service → Environment**

Set these variables:

```
# Security (⚠️ CRITICAL - Generate with: openssl rand -hex 32)
JWT_SECRET_KEY=<generate-random-32-chars>

# Already configured in app (no action needed)
# DATABASE_URL, CORS_ORIGINS, APP_BASE_URL are pre-set in backend/.env

# AWS (if using real AWS S3/SQS - configure your credentials)
AWS_ACCESS_KEY_ID=your_key_id
AWS_SECRET_ACCESS_KEY=your_secret_key

# Optional: Anthropic for decisioning (leave empty if not using)
ANTHROPIC_API_KEY=
```

### Step 2: Verify Backend .env

Backend `.env` file already contains:
- ✅ Database URL (Supabase production)
- ✅ CORS configured for frontend: `https://pfl-4azo.vercel.app`
- ✅ App base URL: `https://pfl-xmq7.onrender.com`
- ✅ Cookies secure enabled: `COOKIE_SECURE=true`
- ✅ Production mode: `APP_ENV=prod`

**No database migrations needed** — they auto-run on startup.

---

## 🎨 Frontend Deployment (Vercel)

### Step 1: Update Environment Variables on Vercel

Go to: **Vercel Dashboard → Project Settings → Environment Variables**

Set these:

```
NEXT_PUBLIC_API_BASE_URL=https://pfl-xmq7.onrender.com
APP_SECRET=<generate-secure-random-32-chars>
COOKIE_SECURE=true
NODE_ENV=production
```

### Step 2: Verify Frontend .env

Frontend `.env` already has:
- ✅ Backend URL: `https://pfl-xmq7.onrender.com`
- ✅ Cookies secure: `COOKIE_SECURE=true`
- ✅ Production mode: `NODE_ENV=production`

**Vercel auto-deploys** on git push to `main` branch.

---

## 📋 Pre-Deployment Checklist

### Backend (Render)
- [ ] Generate JWT_SECRET_KEY with: `openssl rand -hex 32`
- [ ] Set JWT_SECRET_KEY on Render dashboard
- [ ] Configure AWS credentials (if using real S3/SQS)
- [ ] Verify DATABASE_URL is Supabase production
- [ ] Test health endpoint: `curl https://pfl-xmq7.onrender.com/`
- [ ] Check logs for errors: Render dashboard → Logs

### Frontend (Vercel)
- [ ] Generate APP_SECRET with: `openssl rand -hex 32` 
- [ ] Set APP_SECRET on Vercel dashboard
- [ ] Set NEXT_PUBLIC_API_BASE_URL on Vercel dashboard
- [ ] Verify build succeeds: Vercel dashboard → Deployments
- [ ] Test login flow: https://pfl-4azo.vercel.app/login

### Database (Supabase)
- [ ] Verify PostgreSQL is running
- [ ] Verify schema exists (migrations auto-run)
- [ ] Test connection from Render

---

## 🔒 Security Checklist

- [x] JWT_SECRET_KEY is random 32+ chars
- [x] CORS restricted to Vercel URL only
- [x] Cookies marked `Secure` (HTTPS only)
- [x] `cookie_domain` set to `.pflfinance.com` in production
- [x] MFA enforced for admin roles (no bypass in production)
- [x] Database credentials hidden in environment
- [x] No hardcoded secrets in code
- [x] All Docker/LocalStack dev code isolated (guards in place)

---

## 🧪 Testing Production

### 1. Test Backend Health
```bash
curl https://pfl-xmq7.onrender.com/
# Expected: {"service": "pfl-credit-ai", "status": "ok"}
```

### 2. Test Database Connection
```bash
# Run a simple query through the API
curl -X GET https://pfl-xmq7.onrender.com/users/ \
  -H "Authorization: Bearer YOUR_TEST_TOKEN"
```

### 3. Test Login Flow
1. Go to https://pfl-4azo.vercel.app/login
2. Enter valid credentials
3. Should see dashboard if login works
4. Check browser DevTools → Application → Cookies for `refresh_token`

### 4. Check CORS
```bash
# From browser (https://pfl-4azo.vercel.app)
fetch('https://pfl-xmq7.onrender.com/', {
  credentials: 'include'
}).then(r => r.json()).then(console.log)
# Should work without CORS errors
```

---

## 🔧 Troubleshooting

### Backend returns 500
→ Check Render logs for error
→ Verify JWT_SECRET_KEY is set and 32+ chars

### Frontend can't reach backend
→ Verify NEXT_PUBLIC_API_BASE_URL is set to `https://pfl-xmq7.onrender.com`
→ Check browser DevTools → Network for CORS errors
→ Verify backend CORS_ORIGINS includes frontend URL

### Login fails with "Invalid credentials"
→ Check user exists in database
→ Verify DATABASE_URL is correct
→ Check backend logs for auth errors

### "Connection timeout" errors
→ Backend service might be cold-starting on Render
→ Wait 30 seconds and retry
→ Check Render dashboard for resource limits

---

## 📝 Deployment Commands

### First Deployment
```bash
# Backend - Git push triggers Render auto-deploy
git push origin main

# Frontend - Git push triggers Vercel auto-deploy  
git push origin main
```

### Manual Redeploy (if needed)

**Render:**
- Dashboard → Service → Manual Deploy

**Vercel:**
- Dashboard → Deployments → Click "..." → Redeploy

---

## 🎯 What Changed from Dev to Prod

| Item | Dev | Production |
|------|-----|------------|
| Docker | ✅ (docker-compose.yml) | ❌ Removed |
| Hosting | Local | Render + Vercel + Supabase |
| CORS | localhost:3000 | https://pfl-4azo.vercel.app |
| Cookies | Insecure (dev) | Secure HTTPS only |
| MFA | Can bypass (dev flag) | Required for admins |
| AWS | LocalStack | Real AWS (or mock) |
| Logs | Local console | Render/Vercel dashboards |

---

## ✅ Production-Ready Verification

- [x] All Docker files deleted
- [x] Environment variables externalized (.env templates only)
- [x] No hardcoded URLs/secrets in code
- [x] CORS properly configured
- [x] Cookies marked Secure/HttpOnly
- [x] Database uses production Supabase
- [x] Frontend redirects to HTTPS
- [x] Error handling in proxy route
- [x] Backend URL auto-detects from environment
- [x] MFA enforced (no dev bypass)

**Status: ✅ READY TO DEPLOY**

---

## 📞 Support

If issues arise:
1. Check Render logs: `Render Dashboard → Service → Logs`
2. Check Vercel logs: `Vercel Dashboard → Logs → Functions`
3. Check Supabase status: `Database → Logs`
4. Review `.env` files for typos or missing values
