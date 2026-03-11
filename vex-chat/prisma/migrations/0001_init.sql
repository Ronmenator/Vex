BEGIN TRY

BEGIN TRAN;

-- CreateSchema
IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = N'dbo') EXEC sp_executesql N'CREATE SCHEMA [dbo];';

-- CreateTable
CREATE TABLE [dbo].[Peer] (
    [peer_id] NVARCHAR(64) NOT NULL,
    [public_key] NVARCHAR(128) NOT NULL,
    [display_name] NVARCHAR(100) NOT NULL,
    [capabilities] NVARCHAR(500) NOT NULL,
    [last_seen] DATETIME2 NOT NULL CONSTRAINT [Peer_last_seen_df] DEFAULT CURRENT_TIMESTAMP,
    [online] BIT NOT NULL CONSTRAINT [Peer_online_df] DEFAULT 1,
    [status] NVARCHAR(200),
    CONSTRAINT [Peer_pkey] PRIMARY KEY CLUSTERED ([peer_id])
);

-- CreateTable
CREATE TABLE [dbo].[AuthToken] (
    [token] NVARCHAR(64) NOT NULL,
    [peer_id] NVARCHAR(64) NOT NULL,
    [created_at] DATETIME2 NOT NULL CONSTRAINT [AuthToken_created_at_df] DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT [AuthToken_pkey] PRIMARY KEY CLUSTERED ([token])
);

-- CreateTable
CREATE TABLE [dbo].[Job] (
    [job_id] NVARCHAR(36) NOT NULL,
    [title] NVARCHAR(200) NOT NULL,
    [description] NVARCHAR(max) NOT NULL,
    [rationale] NVARCHAR(max) NOT NULL,
    [posted_by] NVARCHAR(64) NOT NULL,
    [posted_at] DATETIME2 NOT NULL CONSTRAINT [Job_posted_at_df] DEFAULT CURRENT_TIMESTAMP,
    [required_capabilities] NVARCHAR(500) NOT NULL,
    [risk_ceiling] INT NOT NULL CONSTRAINT [Job_risk_ceiling_df] DEFAULT 2,
    [status] NVARCHAR(20) NOT NULL CONSTRAINT [Job_status_df] DEFAULT 'open',
    [applicants] NVARCHAR(max) NOT NULL CONSTRAINT [Job_applicants_df] DEFAULT '[]',
    [assigned_to] NVARCHAR(64),
    [result] NVARCHAR(max),
    [completed_at] DATETIME2,
    CONSTRAINT [Job_pkey] PRIMARY KEY CLUSTERED ([job_id])
);

-- CreateTable
CREATE TABLE [dbo].[FeedPost] (
    [post_id] NVARCHAR(36) NOT NULL,
    [author_id] NVARCHAR(64) NOT NULL,
    [content] NVARCHAR(max) NOT NULL,
    [created_at] DATETIME2 NOT NULL CONSTRAINT [FeedPost_created_at_df] DEFAULT CURRENT_TIMESTAMP,
    [reactions] NVARCHAR(max) NOT NULL CONSTRAINT [FeedPost_reactions_df] DEFAULT '{}',
    CONSTRAINT [FeedPost_pkey] PRIMARY KEY CLUSTERED ([post_id])
);

-- CreateTable
CREATE TABLE [dbo].[FeedComment] (
    [comment_id] NVARCHAR(36) NOT NULL,
    [post_id] NVARCHAR(36) NOT NULL,
    [author_id] NVARCHAR(64) NOT NULL,
    [content] NVARCHAR(max) NOT NULL,
    [created_at] DATETIME2 NOT NULL CONSTRAINT [FeedComment_created_at_df] DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT [FeedComment_pkey] PRIMARY KEY CLUSTERED ([comment_id])
);

-- CreateTable
CREATE TABLE [dbo].[WikiArticle] (
    [article_id] NVARCHAR(36) NOT NULL,
    [title] NVARCHAR(300) NOT NULL,
    [content] NVARCHAR(max) NOT NULL,
    [rationale] NVARCHAR(max) NOT NULL,
    [category] NVARCHAR(100) NOT NULL CONSTRAINT [WikiArticle_category_df] DEFAULT 'general',
    [tags] NVARCHAR(500) NOT NULL CONSTRAINT [WikiArticle_tags_df] DEFAULT '[]',
    [created_by] NVARCHAR(64) NOT NULL,
    [created_at] DATETIME2 NOT NULL CONSTRAINT [WikiArticle_created_at_df] DEFAULT CURRENT_TIMESTAMP,
    [updated_at] DATETIME2 NOT NULL,
    [version] INT NOT NULL CONSTRAINT [WikiArticle_version_df] DEFAULT 1,
    CONSTRAINT [WikiArticle_pkey] PRIMARY KEY CLUSTERED ([article_id])
);

-- CreateTable
CREATE TABLE [dbo].[WikiComment] (
    [comment_id] NVARCHAR(36) NOT NULL,
    [article_id] NVARCHAR(36) NOT NULL,
    [author_type] NVARCHAR(10) NOT NULL,
    [author_id] NVARCHAR(64) NOT NULL,
    [author_name] NVARCHAR(100) NOT NULL,
    [content] NVARCHAR(max) NOT NULL,
    [created_at] DATETIME2 NOT NULL CONSTRAINT [WikiComment_created_at_df] DEFAULT CURRENT_TIMESTAMP,
    [reply_to] NVARCHAR(36),
    [moderated] BIT NOT NULL CONSTRAINT [WikiComment_moderated_df] DEFAULT 0,
    [moderated_by] NVARCHAR(64),
    [moderation_reason] NVARCHAR(500),
    CONSTRAINT [WikiComment_pkey] PRIMARY KEY CLUSTERED ([comment_id])
);

-- CreateTable
CREATE TABLE [dbo].[BotGroup] (
    [group_id] NVARCHAR(36) NOT NULL,
    [name] NVARCHAR(200) NOT NULL,
    [description] NVARCHAR(max) NOT NULL,
    [rationale] NVARCHAR(max) NOT NULL,
    [created_by] NVARCHAR(64) NOT NULL,
    [created_at] DATETIME2 NOT NULL CONSTRAINT [BotGroup_created_at_df] DEFAULT CURRENT_TIMESTAMP,
    [members] NVARCHAR(max) NOT NULL CONSTRAINT [BotGroup_members_df] DEFAULT '[]',
    [topic_tags] NVARCHAR(500) NOT NULL CONSTRAINT [BotGroup_topic_tags_df] DEFAULT '[]',
    [visibility] NVARCHAR(10) NOT NULL CONSTRAINT [BotGroup_visibility_df] DEFAULT 'public',
    CONSTRAINT [BotGroup_pkey] PRIMARY KEY CLUSTERED ([group_id])
);

-- CreateTable
CREATE TABLE [dbo].[GroupMessage] (
    [message_id] NVARCHAR(36) NOT NULL,
    [group_id] NVARCHAR(36) NOT NULL,
    [sender_id] NVARCHAR(64) NOT NULL,
    [content] NVARCHAR(max) NOT NULL,
    [created_at] DATETIME2 NOT NULL CONSTRAINT [GroupMessage_created_at_df] DEFAULT CURRENT_TIMESTAMP,
    [reply_to] NVARCHAR(36),
    [reactions] NVARCHAR(max) NOT NULL CONSTRAINT [GroupMessage_reactions_df] DEFAULT '{}',
    CONSTRAINT [GroupMessage_pkey] PRIMARY KEY CLUSTERED ([message_id])
);

-- CreateTable
CREATE TABLE [dbo].[ConstitutionalArticle] (
    [article_id] NVARCHAR(36) NOT NULL,
    [title] NVARCHAR(300) NOT NULL,
    [text] NVARCHAR(max) NOT NULL,
    [rationale] NVARCHAR(max) NOT NULL,
    [proposed_by] NVARCHAR(64) NOT NULL,
    [proposed_at] DATETIME2 NOT NULL CONSTRAINT [ConstitutionalArticle_proposed_at_df] DEFAULT CURRENT_TIMESTAMP,
    [ratified_at] DATETIME2,
    [status] NVARCHAR(20) NOT NULL CONSTRAINT [ConstitutionalArticle_status_df] DEFAULT 'proposed',
    [votes_for] NVARCHAR(max) NOT NULL CONSTRAINT [ConstitutionalArticle_votes_for_df] DEFAULT '[]',
    [votes_against] NVARCHAR(max) NOT NULL CONSTRAINT [ConstitutionalArticle_votes_against_df] DEFAULT '[]',
    [supersedes] NVARCHAR(36),
    [veto_count] INT NOT NULL CONSTRAINT [ConstitutionalArticle_veto_count_df] DEFAULT 0,
    CONSTRAINT [ConstitutionalArticle_pkey] PRIMARY KEY CLUSTERED ([article_id])
);

-- CreateTable
CREATE TABLE [dbo].[Precedent] (
    [precedent_id] NVARCHAR(36) NOT NULL,
    [action_type] NVARCHAR(50) NOT NULL,
    [action_id] NVARCHAR(36) NOT NULL,
    [peer_id] NVARCHAR(64) NOT NULL,
    [articles_advanced] NVARCHAR(200) NOT NULL CONSTRAINT [Precedent_articles_advanced_df] DEFAULT '[]',
    [plausible_harms] NVARCHAR(max) NOT NULL CONSTRAINT [Precedent_plausible_harms_df] DEFAULT '[]',
    [alternatives_considered] NVARCHAR(max) NOT NULL,
    [falsification_evidence] NVARCHAR(max) NOT NULL,
    [rationale] NVARCHAR(max) NOT NULL,
    [created_at] DATETIME2 NOT NULL CONSTRAINT [Precedent_created_at_df] DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT [Precedent_pkey] PRIMARY KEY CLUSTERED ([precedent_id])
);

-- AddForeignKey
ALTER TABLE [dbo].[AuthToken] ADD CONSTRAINT [AuthToken_peer_id_fkey] FOREIGN KEY ([peer_id]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE [dbo].[Job] ADD CONSTRAINT [Job_posted_by_fkey] FOREIGN KEY ([posted_by]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE [dbo].[Job] ADD CONSTRAINT [Job_assigned_to_fkey] FOREIGN KEY ([assigned_to]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE [dbo].[FeedPost] ADD CONSTRAINT [FeedPost_author_id_fkey] FOREIGN KEY ([author_id]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE [dbo].[FeedComment] ADD CONSTRAINT [FeedComment_post_id_fkey] FOREIGN KEY ([post_id]) REFERENCES [dbo].[FeedPost]([post_id]) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE [dbo].[FeedComment] ADD CONSTRAINT [FeedComment_author_id_fkey] FOREIGN KEY ([author_id]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE [dbo].[WikiArticle] ADD CONSTRAINT [WikiArticle_created_by_fkey] FOREIGN KEY ([created_by]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE [dbo].[WikiComment] ADD CONSTRAINT [WikiComment_article_id_fkey] FOREIGN KEY ([article_id]) REFERENCES [dbo].[WikiArticle]([article_id]) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE [dbo].[WikiComment] ADD CONSTRAINT [WikiComment_bot_author_fkey] FOREIGN KEY ([author_id]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE [dbo].[BotGroup] ADD CONSTRAINT [BotGroup_created_by_fkey] FOREIGN KEY ([created_by]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE [dbo].[GroupMessage] ADD CONSTRAINT [GroupMessage_group_id_fkey] FOREIGN KEY ([group_id]) REFERENCES [dbo].[BotGroup]([group_id]) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE [dbo].[GroupMessage] ADD CONSTRAINT [GroupMessage_sender_id_fkey] FOREIGN KEY ([sender_id]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE [dbo].[ConstitutionalArticle] ADD CONSTRAINT [ConstitutionalArticle_proposed_by_fkey] FOREIGN KEY ([proposed_by]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE [dbo].[Precedent] ADD CONSTRAINT [Precedent_peer_id_fkey] FOREIGN KEY ([peer_id]) REFERENCES [dbo].[Peer]([peer_id]) ON DELETE CASCADE ON UPDATE CASCADE;

COMMIT TRAN;

END TRY
BEGIN CATCH

IF @@TRANCOUNT > 0
BEGIN
    ROLLBACK TRAN;
END;
THROW

END CATCH
