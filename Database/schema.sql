CREATE TABLE users (
    user_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    username VARCHAR(30) NOT NULL UNIQUE,
    full_name VARCHAR(100) NOT NULL,

    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255),

    google_id VARCHAR(255) UNIQUE,

    account_type ENUM(
        'PUBLIC',
        'STUDENT_PENDING',
        'STUDENT_VERIFIED',
        'EMPLOYEE_PENDING',
        'EMPLOYEE_VERIFIED',
        'ADMIN'
    ) DEFAULT 'PUBLIC',

    enrollment_id VARCHAR(30) UNIQUE,
    employee_id VARCHAR(30) UNIQUE,

    profile_picture TEXT,
    bio TEXT,

    storage_used BIGINT DEFAULT 0,
    storage_limit BIGINT DEFAULT 16106127360,

    email_verified BOOLEAN DEFAULT FALSE,
    two_factor_enabled BOOLEAN DEFAULT FALSE,

    account_status ENUM(
        'ACTIVE',
        'SUSPENDED',
        'DELETED'
    ) DEFAULT 'ACTIVE',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL
);

CREATE TABLE workspaces (
    workspace_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    user_id BIGINT NOT NULL,

    workspace_name VARCHAR(100) NOT NULL,

    description TEXT,

    workspace_type ENUM('PERSONAL', 'INSTITUTION') NOT NULL,

    visibility ENUM('PRIVATE', 'SHARED') DEFAULT 'PRIVATE',

    storage_used BIGINT DEFAULT 0,

    storage_limit BIGINT DEFAULT 0,

    color VARCHAR(20) DEFAULT 'blue',

    is_archived BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE
);

CREATE TABLE workspace_members (

    member_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    workspace_id BIGINT NOT NULL,

    user_id BIGINT NOT NULL,

    role ENUM(
        'OWNER',
        'ADMIN',
        'EDITOR',
        'VIEWER'
    ) DEFAULT 'VIEWER',

    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    invited_by BIGINT,

    FOREIGN KEY (workspace_id)
        REFERENCES workspaces(workspace_id)
        ON DELETE CASCADE,

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    FOREIGN KEY (invited_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    UNIQUE (workspace_id, user_id)

);

CREATE TABLE folders (

    folder_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    workspace_id BIGINT NOT NULL,

    parent_folder_id BIGINT NULL,

    folder_name VARCHAR(255) NOT NULL,

    description TEXT,

    color VARCHAR(20) DEFAULT 'blue',

    is_favorite BOOLEAN DEFAULT FALSE,

    is_archived BOOLEAN DEFAULT FALSE,

    created_by BIGINT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (workspace_id)
        REFERENCES workspaces(workspace_id)
        ON DELETE CASCADE,

    FOREIGN KEY (parent_folder_id)
        REFERENCES folders(folder_id)
        ON DELETE CASCADE,

    FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE CASCADE

);

CREATE TABLE files (

    file_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    folder_id BIGINT NOT NULL,

    uploaded_by BIGINT NOT NULL,

    file_name VARCHAR(255) NOT NULL,

    original_file_name VARCHAR(255) NOT NULL,

    file_extension VARCHAR(20),

    mime_type VARCHAR(100),

    file_size BIGINT NOT NULL,

    storage_path TEXT NOT NULL,

    file_hash CHAR(64) NOT NULL,

    ai_enabled BOOLEAN DEFAULT FALSE,

    is_favorite BOOLEAN DEFAULT FALSE,

    is_archived BOOLEAN DEFAULT FALSE,

    is_deleted BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (folder_id)
        REFERENCES folders(folder_id)
        ON DELETE CASCADE,

    FOREIGN KEY (uploaded_by)
        REFERENCES users(user_id)
        ON DELETE CASCADE

);

CREATE TABLE file_versions (

    version_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    file_id BIGINT NOT NULL,

    version_number INT NOT NULL,

    storage_path TEXT NOT NULL,

    file_size BIGINT NOT NULL,

    file_hash CHAR(64) NOT NULL,

    uploaded_by BIGINT NOT NULL,

    version_note TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (file_id)
        REFERENCES files(file_id)
        ON DELETE CASCADE,

    FOREIGN KEY (uploaded_by)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    UNIQUE (file_id, version_number)

);

CREATE TABLE file_shares (

    share_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    file_id BIGINT NOT NULL,

    shared_by BIGINT NOT NULL,

    shared_with BIGINT,

    share_type ENUM('PRIVATE','PUBLIC','LINK') DEFAULT 'PRIVATE',

    permission ENUM('VIEW','EDIT') DEFAULT 'VIEW',

    share_link VARCHAR(255) UNIQUE,

    password_hash VARCHAR(255),

    expires_at TIMESTAMP NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (file_id)
        REFERENCES files(file_id)
        ON DELETE CASCADE,

    FOREIGN KEY (shared_by)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    FOREIGN KEY (shared_with)
        REFERENCES users(user_id)
        ON DELETE CASCADE

);

CREATE TABLE comments (

    comment_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    file_id BIGINT NOT NULL,

    user_id BIGINT NOT NULL,

    comment TEXT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (file_id)
        REFERENCES files(file_id)
        ON DELETE CASCADE,

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE

);

CREATE TABLE activity_logs (

    activity_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    user_id BIGINT NOT NULL,

    file_id BIGINT,

    activity_type VARCHAR(100) NOT NULL,

    activity_description TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    FOREIGN KEY (file_id)
        REFERENCES files(file_id)
        ON DELETE SET NULL

);

CREATE TABLE notifications (

    notification_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    user_id BIGINT NOT NULL,

    title VARCHAR(255) NOT NULL,

    message TEXT NOT NULL,

    is_read BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE

);

CREATE TABLE favorites (

    favorite_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    user_id BIGINT NOT NULL,

    file_id BIGINT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    FOREIGN KEY (file_id)
        REFERENCES files(file_id)
        ON DELETE CASCADE,

    UNIQUE (user_id, file_id)

);

CREATE TABLE tags (

    tag_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    tag_name VARCHAR(100) NOT NULL UNIQUE

);

CREATE TABLE file_tags (

    file_tag_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    file_id BIGINT NOT NULL,

    tag_id BIGINT NOT NULL,

    FOREIGN KEY (file_id)
        REFERENCES files(file_id)
        ON DELETE CASCADE,

    FOREIGN KEY (tag_id)
        REFERENCES tags(tag_id)
        ON DELETE CASCADE,

    UNIQUE (file_id, tag_id)

);