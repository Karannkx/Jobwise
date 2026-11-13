"""Skill vocabulary for reading skills out of raw job text without calling an AI.

Canonical names are lower-case and match ``scoring.norm_skill`` output, so a candidate skill such as
"PostgreSQL" or "Postgres" lines up with the job skill "postgresql". Soft skills (communication,
teamwork ...) are deliberately left out: they appear in almost every posting and carry no signal.
"""

from __future__ import annotations

# canonical name -> extra spellings that are safe to match in running text
SKILLS: dict[str, list[str]] = {
    # languages
    "python": ["python3"], "java": [], "javascript": ["js", "ecmascript"], "typescript": [], "c++": ["cpp"],
    "c#": ["csharp"], "golang": ["go lang"], "rust": [], "kotlin": [], "swift": [], "php": [], "ruby": [],
    "scala": [], "r programming": [], "matlab": [], "sql": [], "bash": ["shell scripting"], "perl": [],
    "dart": [], "objective-c": [], "solidity": [], "powershell": [], "vba": [],
    # web / backend
    "html": ["html5"], "css": ["css3"], "sass": [], "react": ["reactjs", "react.js"], "react native": [],
    "angular": ["angularjs"], "vue": ["vuejs", "vue.js"], "next.js": ["nextjs"], "nuxt": [], "svelte": [],
    "node.js": ["nodejs", "node js"], "express": ["express.js"], "django": [], "flask": [], "fastapi": [],
    "spring boot": [], "spring": [], "laravel": [], "ruby on rails": ["rails"], "asp.net": [], ".net": ["dotnet"],
    "graphql": [], "rest api": ["rest apis", "restful api", "restful apis", "restful services"], "grpc": [],
    "websockets": [], "jquery": [], "tailwind": ["tailwind css"], "bootstrap": [], "redux": [], "webpack": [],
    # mobile
    "android": [], "ios": [], "flutter": [], "xamarin": [],
    # data / ml
    "machine learning": ["ml"], "deep learning": [], "natural language processing": ["nlp"],
    "computer vision": [], "tensorflow": [], "pytorch": [], "keras": [], "scikit-learn": ["sklearn", "scikit learn"],
    "pandas": [], "numpy": [], "spark": ["apache spark", "pyspark"], "hadoop": [], "kafka": ["apache kafka"],
    "airflow": ["apache airflow"], "dbt": [], "etl": [], "data warehousing": ["data warehouse"],
    "data modeling": ["data modelling"], "data analysis": ["data analytics"], "data visualization": ["data visualisation"],
    "tableau": [], "powerbi": ["power bi"], "looker": [], "excel": ["microsoft excel", "ms excel"],
    "statistics": ["statistical analysis"], "a/b testing": ["ab testing"], "llm": ["llms", "large language models"],
    "generative ai": ["genai", "gen ai"], "mlops": [], "opencv": [], "hugging face": ["huggingface"], "langchain": [],
    "snowflake": [], "bigquery": [], "redshift": [], "databricks": [], "data engineering": [], "data science": [],
    # databases
    "postgresql": ["postgres"], "mysql": [], "mongodb": ["mongo"], "redis": [], "elasticsearch": [],
    "oracle": ["oracle db"], "sql server": ["mssql", "ms sql server"], "sqlite": [], "cassandra": [],
    "dynamodb": [], "neo4j": [], "nosql": [],
    # cloud / devops
    "aws": ["amazon web services"], "azure": ["microsoft azure"], "google cloud": ["gcp", "google cloud platform"],
    "docker": [], "kubernetes": ["k8s"], "terraform": [], "ansible": [], "jenkins": [], "ci/cd": ["cicd", "ci cd"],
    "github actions": [], "gitlab": ["gitlab ci"], "git": [], "linux": [], "nginx": [], "prometheus": [],
    "grafana": [], "devops": [], "sre": ["site reliability"], "microservices": [], "serverless": [],
    "cloudformation": [], "helm": [], "observability": [],
    # quality / process
    "unit testing": [], "selenium": [], "cypress": [], "jest": [], "pytest": [], "junit": [],
    "test automation": ["automation testing"], "manual testing": [], "agile": [], "scrum": [], "jira": [],
    "system design": [], "data structures": [], "algorithms": [], "object-oriented programming": ["oop"],
    "design patterns": [], "api design": [],
    # security
    "cybersecurity": ["cyber security", "information security"], "penetration testing": ["pentesting"],
    "owasp": [], "siem": [], "iam": [], "network security": [],
    # design / product
    "figma": [], "ui design": ["ui/ux"], "ux design": ["ux research"], "adobe photoshop": ["photoshop"],
    "adobe illustrator": ["illustrator"], "product management": ["product manager"], "wireframing": [],
    "user research": [], "prototyping": [],
    # marketing / sales
    "seo": [], "sem": [], "google analytics": [], "google ads": ["adwords"], "content marketing": [],
    "social media marketing": ["social media"], "email marketing": [], "hubspot": [], "salesforce": [],
    "crm": [], "copywriting": [], "lead generation": [], "b2b sales": [], "cold calling": [],
    "digital marketing": [], "performance marketing": [],
    # finance / ops / hr
    "accounting": [], "financial modeling": ["financial modelling"], "financial analysis": [], "budgeting": [],
    "auditing": ["audit"], "gst": [], "taxation": [], "tally": [], "sap": [], "quickbooks": [], "erp": [],
    "recruitment": ["talent acquisition"], "payroll": [], "hris": [], "supply chain": [], "logistics": [],
    "procurement": [], "project management": [], "pmp": [], "stakeholder management": [],
    "customer support": ["customer service"], "customer success": [], "zendesk": [],
}

# Words that name a role but say nothing about a *skill*; they are not used as feed-filter tokens.
GENERIC_ROLE_WORDS = {
    "senior", "junior", "lead", "principal", "staff", "manager", "engineer", "developer", "specialist",
    "associate", "intern", "analyst", "consultant", "executive", "officer", "head", "director", "software",
    "full", "stack", "full-stack", "remote", "the", "and", "for", "with", "sr", "jr",
}
