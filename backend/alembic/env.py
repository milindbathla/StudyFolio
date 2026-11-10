from alembic import context

context.configure(connection=context.config.attributes["connection"], render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
