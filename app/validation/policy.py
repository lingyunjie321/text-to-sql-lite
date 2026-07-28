from sqlglot import exp

from app.connectors.errors import ErrorType
from app.validation.models import POLICY_VERSION, ValidationIssue


PARSE_ERROR = ValidationIssue(
    ErrorType.SYNTAX_ERROR,
    "SQL_PARSE_ERROR",
    "The SQL statement is invalid.",
)
MULTIPLE_STATEMENTS = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_MULTIPLE_STATEMENTS",
    "The SQL statement is not permitted.",
)
NOT_READ_ONLY = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_NOT_READ_ONLY",
    "The SQL statement is not permitted.",
)
FORBIDDEN_NODE = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_FORBIDDEN_NODE",
    "The SQL statement is not permitted.",
)
WILDCARD_FORBIDDEN = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_WILDCARD_FORBIDDEN",
    "The SQL statement is not permitted.",
)
UNKNOWN_AST = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_UNKNOWN_AST",
    "The SQL statement is not permitted.",
)
DIALECT_ERROR = ValidationIssue(
    ErrorType.DIALECT_ERROR,
    "SQL_DIALECT_ERROR",
    "The SQL dialect is not supported.",
)
FUNCTION_NOT_ALLOWED = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_FUNCTION_NOT_ALLOWED",
    "The SQL statement uses a function that is not permitted.",
)
CONTEXT_INVALID = ValidationIssue(
    ErrorType.UNKNOWN,
    "SQL_VALIDATION_CONTEXT_INVALID",
    "The SQL validation context is invalid.",
)
OBJECT_NOT_ALLOWED = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_OBJECT_NOT_ALLOWED",
    "The SQL statement references an object that is not permitted.",
)
OBJECT_AMBIGUOUS = ValidationIssue(
    ErrorType.SCHEMA_ERROR,
    "SQL_OBJECT_AMBIGUOUS",
    "The SQL statement contains an ambiguous database object.",
)
OBJECT_UNKNOWN = ValidationIssue(
    ErrorType.SCHEMA_ERROR,
    "SQL_OBJECT_UNKNOWN",
    "The SQL statement references an invalid database object.",
)
COLUMN_INVALID = ValidationIssue(
    ErrorType.SCHEMA_ERROR,
    "SQL_COLUMN_INVALID",
    "The SQL statement references an invalid or ambiguous field.",
)

ALLOWED_FUNCTION_NAMES = {
    exp.Count: "COUNT",
    exp.Sum: "SUM",
    exp.Avg: "AVG",
    exp.Min: "MIN",
    exp.Max: "MAX",
    exp.Coalesce: "COALESCE",
    exp.Nullif: "NULLIF",
    exp.Lower: "LOWER",
    exp.Upper: "UPPER",
    exp.Length: "LENGTH",
    exp.Trim: "TRIM",
    exp.Substring: "SUBSTRING",
    exp.TimestampTrunc: "DATE_TRUNC",
    exp.Extract: "EXTRACT",
    exp.CurrentDate: "CURRENT_DATE",
    exp.Round: "ROUND",
    exp.Abs: "ABS",
    exp.Ceil: "CEIL",
    exp.Floor: "FLOOR",
    exp.Case: "CASE",
    exp.Cast: "CAST",
}
ALLOWED_FUNCTIONS = tuple(
    sorted(set(ALLOWED_FUNCTION_NAMES.values()))
)

ALLOWED_CAST_TARGET_TYPES = frozenset(
    {
        exp.DataType.Type.BOOLEAN,
        exp.DataType.Type.SMALLINT,
        exp.DataType.Type.INT,
        exp.DataType.Type.BIGINT,
        exp.DataType.Type.DECIMAL,
        exp.DataType.Type.FLOAT,
        exp.DataType.Type.DOUBLE,
        exp.DataType.Type.CHAR,
        exp.DataType.Type.BPCHAR,
        exp.DataType.Type.VARCHAR,
        exp.DataType.Type.TEXT,
        exp.DataType.Type.DATE,
        exp.DataType.Type.TIME,
        exp.DataType.Type.TIMETZ,
        exp.DataType.Type.TIMESTAMP,
        exp.DataType.Type.TIMESTAMPTZ,
        exp.DataType.Type.INTERVAL,
        exp.DataType.Type.JSON,
        exp.DataType.Type.JSONB,
        exp.DataType.Type.UUID,
    }
)

MAX_CAST_TYPE_PARAMETERS = {
    exp.DataType.Type.CHAR: 1,
    exp.DataType.Type.BPCHAR: 1,
    exp.DataType.Type.VARCHAR: 1,
    exp.DataType.Type.DECIMAL: 2,
    exp.DataType.Type.FLOAT: 1,
    exp.DataType.Type.TIME: 1,
    exp.DataType.Type.TIMETZ: 1,
    exp.DataType.Type.TIMESTAMP: 1,
    exp.DataType.Type.TIMESTAMPTZ: 1,
    exp.DataType.Type.INTERVAL: 1,
}

FORBIDDEN_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Alter,
    exp.Drop,
    exp.TruncateTable,
    exp.Copy,
    exp.Command,
    exp.Set,
    exp.Into,
    exp.Lock,
)

ALLOWED_NON_FUNCTION_NODE_TYPES = frozenset(
    {
        exp.Select,
        exp.From,
        exp.Join,
        exp.Subquery,
        exp.CTE,
        exp.With,
        exp.Alias,
        exp.TableAlias,
        exp.Table,
        exp.Column,
        exp.Identifier,
        exp.Literal,
        exp.Null,
        exp.Boolean,
        exp.Where,
        exp.Group,
        exp.Having,
        exp.Order,
        exp.Ordered,
        exp.Limit,
        exp.Distinct,
        exp.Star,
        exp.DataType,
        exp.DataTypeParam,
        exp.Var,
        exp.Exists,
        exp.Paren,
        exp.Not,
        exp.And,
        exp.Or,
        exp.EQ,
        exp.NEQ,
        exp.GT,
        exp.GTE,
        exp.LT,
        exp.LTE,
        exp.Is,
        exp.Between,
        exp.In,
        exp.Like,
        exp.ILike,
        exp.Add,
        exp.Sub,
        exp.Mul,
        exp.Div,
        exp.Mod,
        exp.Neg,
    }
)

__all__ = ["POLICY_VERSION"]
